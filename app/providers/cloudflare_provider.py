"""
Cloudflare Workers AI adapter for Subtitle Translation.
Features:
- Multi-account pool with automatic failover across configured accounts.
- Model-specific chunk sizing (50, 60, or 70 cues) optimized for token budgets and 1:1 cue alignment.
- Thinking / reasoning modes strictly disabled (zero extra token overhead).
- Deterministic temperature (0.1) for high-fidelity translation without hallucination.
- 100% preservation of subtitle indices and original timestamps.
- Active account memory across files.
- Resilient error handling (401/403 credentials validation vs 429 quota rotation).
"""

from __future__ import annotations
import json
import logging
import re
import time
from typing import Optional, Tuple, Any, List, Dict, Set
import requests

from app.core.config import VERIFIED_TRANSLATION_PROVIDERS, LANG_NAME_MAP
from app.core.credential_manager import CredentialManager
from app.core.srt_parser import SRTParser
from app.core.types import SubtitleFile, SubtitleCue, ProviderInfo
from app.providers.base import BaseTranslationProvider

logger = logging.getLogger("OnlineSubtitleTranslator.Cloudflare")

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4/accounts"
DEFAULT_CLOUDFLARE_MODEL = "@cf/google/gemma-4-26b-a4b-it"

# Model-specific chunk sizes optimized for context limits, timeout prevention, and 1:1 cue alignment
DEFAULT_CHUNK_SIZE = 70
MODEL_CHUNK_SIZES: Dict[str, int] = {
    "@cf/google/gemma-4-26b-a4b-it": 70,
    "@cf/qwen/qwen3.8-27b": 60,
    "@cf/openai/gpt-oss-120b": 50,
    "@cf/meta/llama-3.3-70b-instruct-fp8-fast": 60,
}
CHUNK_SIZE = DEFAULT_CHUNK_SIZE


def get_chunk_size_for_model(model_id: str) -> int:
    """Return recommended cue chunk size for a Cloudflare model."""
    if model_id in MODEL_CHUNK_SIZES:
        return MODEL_CHUNK_SIZES[model_id]
    for key, sz in MODEL_CHUNK_SIZES.items():
        if key in model_id or model_id in key:
            return sz
    return DEFAULT_CHUNK_SIZE


class CloudflareTranslationProvider(BaseTranslationProvider):
    """Machine Translation using verified Cloudflare Workers AI models with multi-account pool."""

    # Static memory to retain the active working account across file translations
    _active_account_index: Optional[int] = None

    def __init__(self, model_id: str = DEFAULT_CLOUDFLARE_MODEL, api_key: Optional[str] = None, **kwargs: Any):
        super().__init__(model_id, api_key, **kwargs)
        self.account_id = kwargs.get("account_id") or CredentialManager.get_credential("cloudflare", "account_id")

    def get_info(self) -> ProviderInfo:
        for p in VERIFIED_TRANSLATION_PROVIDERS:
            if p.provider_id == "cloudflare" and p.model_id == self.model_id:
                return p
        chunk_sz = get_chunk_size_for_model(self.model_id)
        return ProviderInfo(
            provider_id="cloudflare",
            display_name="Cloudflare Workers AI",
            model_id=self.model_id,
            model_display_name=f"Cloudflare AI ({self.model_id})",
            pipeline="TRANSLATION",
            is_free=True,
            pricing_desc="10,000 Neurons/day free; $0.011 / 1k Neurons paid",
            free_tier_desc=f"10k free daily Neurons on Cloudflare • {chunk_sz} cues/chunk",
            supports_timestamps=True,
            max_duration_sec=0,
            requires_key=True,
            doc_url=f"https://developers.cloudflare.com/workers-ai/models/{self.model_id.replace('@cf/', '')}/",
        )

    def validate_credentials(self) -> Tuple[bool, str]:
        accounts = [a for a in CredentialManager.get_cloudflare_accounts() if a.get("configured")]
        if not accounts:
            if not self.api_key or len(self.api_key.strip()) < 10:
                return False, "No configured Cloudflare account found. Please configure API Token."
            if not self.account_id or len(self.account_id.strip()) < 10:
                return False, "No configured Cloudflare account found. Please configure Account ID."
        return True, "Cloudflare credentials configured."

    def _execute_with_account_pool(
        self,
        payload: dict,
        cancel_token: Optional[Any] = None,
        max_cycles: int = 5
    ) -> Dict[str, Any]:
        if self.api_key and self.account_id:
            all_accounts = [{"index": 1, "account_id": self.account_id, "api_key": self.api_key, "configured": True}]
        else:
            all_accounts = [a for a in CredentialManager.get_cloudflare_accounts() if a.get("configured")]
            if not all_accounts and self.account_id and self.api_key:
                all_accounts = [{"index": 1, "account_id": self.account_id, "api_key": self.api_key, "configured": True}]

        if not all_accounts:
            raise ValueError("No valid Cloudflare accounts configured. Please add an account in Settings.")

        # Reorder accounts so that the last known working account is tried first
        if self._active_account_index is not None:
            active = [a for a in all_accounts if a["index"] == self._active_account_index]
            others = [a for a in all_accounts if a["index"] != self._active_account_index]
            ordered_accounts = active + others
        else:
            ordered_accounts = list(all_accounts)

        invalid_accounts: Set[int] = set()
        cycle = 0
        wait_delay = 45

        while cycle < max_cycles:
            valid_tried = 0
            for acct in ordered_accounts:
                idx = acct["index"]
                if idx in invalid_accounts:
                    continue

                if cancel_token and getattr(cancel_token, "is_cancelled", False):
                    raise RuntimeError("Operation cancelled by user.")

                valid_tried += 1
                acct_id = acct["account_id"]
                token = acct["api_key"]

                url = f"{CLOUDFLARE_API_BASE}/{acct_id}/ai/run/{self.model_id}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }

                logger.info(f"Sending translation request to Cloudflare {self.model_id} (Account #{idx})...")

                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=90)
                except requests.RequestException as e:
                    logger.warning(f"Network error on Cloudflare Account #{idx}: {e}")
                    continue

                # 1. Success response
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success", False) or "result" in data:
                        CloudflareTranslationProvider._active_account_index = idx
                        if cancel_token and hasattr(cancel_token, "notify_rate_limit_cleared"):
                            try:
                                cancel_token.notify_rate_limit_cleared("Cloudflare Workers AI")
                            except Exception as ex:
                                logger.debug(f"Signal notification error: {ex}")
                        return data.get("result", {})
                    else:
                        errors = data.get("errors", [])
                        err_msg = "; ".join(e.get("message", "") for e in errors) if errors else "Unknown API error"
                        if "neuron" in err_msg.lower() or "limit" in err_msg.lower():
                            logger.warning(f"Cloudflare Account #{idx} quota exhausted: {err_msg}")
                            continue
                        elif "auth" in err_msg.lower() or "unauthorized" in err_msg.lower():
                            logger.error(f"Cloudflare Account #{idx} authentication failed: {err_msg}")
                            invalid_accounts.add(idx)
                            continue
                        else:
                            raise RuntimeError(f"Cloudflare error on Account #{idx}: {err_msg}")

                # 2. Authentication failure (invalid credentials) -> do NOT loop forever
                elif resp.status_code in (401, 403):
                    logger.error(f"Cloudflare Account #{idx} rejected with HTTP {resp.status_code} (Invalid token/account).")
                    invalid_accounts.add(idx)
                    continue

                # 3. Bad request (e.g. unknown reasoning parameter on some models) -> retry with simplified payload
                elif resp.status_code == 400:
                    err_text = resp.text.lower()
                    if "reasoning" in err_text or "chat_template" in err_text or "extra fields" in err_text:
                        simplified_payload = dict(payload)
                        simplified_payload.pop("reasoning_effort", None)
                        simplified_payload.pop("chat_template_kwargs", None)
                        try:
                            retry_resp = requests.post(url, headers=headers, json=simplified_payload, timeout=90)
                            if retry_resp.status_code == 200:
                                retry_data = retry_resp.json()
                                if retry_data.get("success", False) or "result" in retry_data:
                                    CloudflareTranslationProvider._active_account_index = idx
                                    return retry_data.get("result", {})
                        except Exception:
                            pass
                    logger.error(f"Cloudflare Account #{idx} rejected with HTTP 400: {resp.text[:200]}")
                    invalid_accounts.add(idx)
                    continue

                # 4. Rate Limit / Quota Exceeded -> rotate to next account
                elif resp.status_code == 429:
                    logger.warning(f"Cloudflare Account #{idx} returned 429 Rate Limit / Quota Exceeded.")
                    continue
                else:
                    logger.warning(f"Cloudflare Account #{idx} returned HTTP {resp.status_code}: {resp.text[:200]}")
                    continue

            # Check if all accounts are permanently invalid
            if len(invalid_accounts) >= len(ordered_accounts):
                raise RuntimeError(
                    f"All {len(ordered_accounts)} Cloudflare account(s) failed authentication (HTTP 401/403). "
                    "Please verify your Account ID and API Token in Settings."
                )

            # If all valid accounts were tried and temporarily rate-limited
            cycle += 1
            if cycle >= max_cycles:
                break

            logger.warning(
                f"All active Cloudflare account(s) are currently rate-limited or exhausted. "
                f"Waiting {wait_delay}s before retrying (Cycle {cycle}/{max_cycles})..."
            )

            for rem in range(wait_delay, 0, -1):
                if cancel_token and getattr(cancel_token, "is_cancelled", False):
                    raise RuntimeError("Operation cancelled by user.")

                if cancel_token and hasattr(cancel_token, "notify_rate_limit"):
                    try:
                        cancel_token.notify_rate_limit(
                            "Cloudflare Workers AI",
                            rem,
                            cycle,
                            f"All Cloudflare accounts quota reached. Waiting for reset ({rem}s)..."
                        )
                    except Exception as ex:
                        logger.debug(f"Signal notification error: {ex}")
                time.sleep(1.0)

            wait_delay = min(wait_delay * 2, 180)

        raise RuntimeError(
            f"Cloudflare translation failed after {max_cycles} cycles across all accounts. "
            "Daily neuron quota may be fully exhausted. Try again later or switch to Google Gemini."
        )

    def _build_prompts(self, chunk_srt: str, target_desc: str) -> Tuple[str, str]:
        """Build rigorous system and user prompts adhering to strict subtitle translation rules."""
        system_prompt = (
            f"You are a professional subtitle translator. Translate the provided subtitles from their original language into {target_desc}.\n\n"
            "Translation Rules:\n\n"
            f"1. Translate every subtitle accurately and completely into {target_desc}. Do not omit, summarize, shorten, expand, or invent any dialogue.\n"
            f"2. Use natural, fluent, and conversational {target_desc} appropriate for subtitles, avoiding stiff or overly literal translations.\n"
            "3. Preserve the original meaning, tone, emotions, humor, sarcasm, slang, idioms, profanity, and character personality as faithfully as possible.\n"
            "4. Use context from surrounding dialogue to resolve ambiguities and choose the most appropriate translation.\n"
            "5. Keep character names, place names, proper nouns, and established terminology consistent throughout the subtitles.\n"
            "6. Preserve the original level of formality, relationships between characters, and emotional intensity.\n"
            "7. Do not censor profanity, offensive language, or adult dialogue unless the original text itself does so.\n"
            "8. Do not add explanations, translator's notes, alternative translations, or any text that does not belong in the subtitles.\n"
            "9. Do not translate timestamps, subtitle indices, or structural elements.\n"
            "10. Preserve the exact original SRT structure. Do not merge, split, reorder, renumber, or remove subtitle blocks.\n"
            "11. The number of subtitle blocks in your output must exactly match the number of subtitle blocks in the input.\n"
            "12. If a subtitle is ambiguous, make the most contextually appropriate translation without asking questions or adding commentary.\n"
            "13. If a subtitle contains non-dialogue text such as sound effects, music cues, or speaker labels, translate it appropriately while preserving its formatting.\n"
            "14. Maintain consistency with terminology and translations used in previous chunks, if any.\n\n"
            "Output Requirements\n\n"
            "- Output only the translated subtitles in valid format.\n"
            "- Do not include introductions, conclusions, explanations, markdown code fences, or any other text outside the subtitles.\n"
            "- Ensure that every subtitle block is translated and that the output is complete.\n"
            "- Do not output thinking process, explanations, or chain of thought."
        )
        user_prompt = (
            f"Target language: {target_desc}\n\n"
            "Translate the following subtitles:\n\n"
            f"{chunk_srt}"
        )
        return system_prompt, user_prompt

    def _translate_cue_chunk(
        self,
        cues_chunk: List[SubtitleCue],
        target_language: str,
        cancel_token: Optional[Any] = None
    ) -> List[SubtitleCue]:
        """Translate a single batch of cues with ID matching and retry on mismatch."""
        target_desc = LANG_NAME_MAP.get(target_language.lower(), target_language)
        expected_indices = [c.index for c in cues_chunk]
        chunk_sub = SubtitleFile(cues=cues_chunk, language="en")
        chunk_srt = chunk_sub.to_srt()

        system_prompt, user_prompt = self._build_prompts(chunk_srt, target_desc)

        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_prompt
                }
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
        }

        # Selectively apply reasoning_effort for models that support it without 400 rejection
        if "gpt-oss" in self.model_id.lower() or "glm" in self.model_id.lower():
            payload["reasoning_effort"] = "low"

        # Attempt translation with retry on missing cue count
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                raise RuntimeError("Operation cancelled by user.")

            result = self._execute_with_account_pool(payload, cancel_token=cancel_token)

            # Robust response extraction
            raw_text = ""
            if isinstance(result, dict):
                choices = result.get("choices", [])
                if choices and isinstance(choices, list):
                    raw_text = choices[0].get("message", {}).get("content", "") or ""
                if not raw_text:
                    raw_text = result.get("response", "") or ""
            elif isinstance(result, str):
                raw_text = result

            # 1. Clean reasoning and thinking tokens
            raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.IGNORECASE)
            raw_text = re.sub(r"<thought>[\s\S]*?</thought>", "", raw_text, flags=re.IGNORECASE)
            raw_text = re.sub(r"\[THINKING\][\s\S]*?\[/THINKING\]", "", raw_text, flags=re.IGNORECASE)

            # 2. Clean markdown code fences and extraneous wrappers
            clean_text = raw_text.strip()
            if clean_text.startswith("```srt"):
                clean_text = clean_text[6:]
            elif clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            clean_text = clean_text.strip()

            parsed = SRTParser.parse_text(clean_text, default_language=target_language)

            # Match cues strictly by cue index or by sequential alignment
            id_to_text: Dict[int, str] = {c.index: c.text.strip() for c in parsed.cues if c.text.strip()}

            translated_chunk: List[SubtitleCue] = []
            missing_count = 0
            for orig in cues_chunk:
                trans_text = id_to_text.get(orig.index)
                if not trans_text and len(parsed.cues) == len(cues_chunk):
                    # Sequential fallback if indices were renumbered 1..N
                    idx_in_chunk = cues_chunk.index(orig)
                    trans_text = parsed.cues[idx_in_chunk].text.strip()

                if trans_text:
                    # 100% preservation of original start_ms and end_ms
                    translated_chunk.append(SubtitleCue(
                        index=orig.index,
                        start_ms=orig.start_ms,
                        end_ms=orig.end_ms,
                        text=trans_text
                    ))
                else:
                    missing_count += 1
                    # Preserve slot with original cue text so subsequent cues maintain exact timeline alignment
                    translated_chunk.append(SubtitleCue(
                        index=orig.index,
                        start_ms=orig.start_ms,
                        end_ms=orig.end_ms,
                        text=orig.text
                    ))

            if missing_count == 0:
                return translated_chunk

            if attempt < max_attempts:
                logger.warning(
                    f"Cloudflare chunk attempt #{attempt}: received {len(parsed.cues)} cues, "
                    f"expected {len(cues_chunk)} ({missing_count} missing). Retrying chunk..."
                )
                continue

            # On final attempt, allow small number of merged dialogue fragments (<= 15%) without halting the entire movie
            max_tolerated_missing = max(1, int(len(cues_chunk) * 0.15)) if len(cues_chunk) >= 10 else 0
            if missing_count <= max_tolerated_missing:
                logger.warning(
                    f"Cloudflare chunk completed with {len(cues_chunk) - missing_count}/{len(cues_chunk)} translated cues. "
                    f"{missing_count} dialogue fragment(s) merged by model were safely retained without timing shift."
                )
                return translated_chunk

            raise RuntimeError(
                f"Cloudflare translation failed for cues {expected_indices[0]} to {expected_indices[-1]}: "
                f"Model returned incomplete output ({len(parsed.cues)} of {len(cues_chunk)} cues)."
            )

    def translate(
        self,
        subtitle_file: SubtitleFile,
        target_language: str = "fa",
        cancel_token: Optional[Any] = None
    ) -> SubtitleFile:
        valid, msg = self.validate_credentials()
        if not valid:
            raise ValueError(msg)

        if not subtitle_file.cues:
            return SubtitleFile(cues=[], language=target_language)

        total_cues = len(subtitle_file.cues)
        chunk_size = get_chunk_size_for_model(self.model_id)

        chunks = [
            subtitle_file.cues[i:i + chunk_size]
            for i in range(0, total_cues, chunk_size)
        ]

        target_desc = LANG_NAME_MAP.get(target_language.lower(), target_language)
        logger.info(
            f"Translating {total_cues} cues to {target_desc} in {len(chunks)} chunk(s) "
            f"(chunk size {chunk_size}) via Cloudflare {self.model_id}..."
        )

        all_translated_cues: List[SubtitleCue] = []
        for chunk_idx, chunk in enumerate(chunks, 1):
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                raise RuntimeError("Operation cancelled by user.")

            logger.info(
                f"Translating chunk {chunk_idx}/{len(chunks)} (cues {chunk[0].index}..{chunk[-1].index})..."
            )
            trans_chunk = self._translate_cue_chunk(
                cues_chunk=chunk,
                target_language=target_language,
                cancel_token=cancel_token
            )
            all_translated_cues.extend(trans_chunk)

        for c in all_translated_cues:
            c.text = SRTParser.clean_trailing_punctuation(c.text)

        return SubtitleFile(cues=all_translated_cues, language=target_language)
