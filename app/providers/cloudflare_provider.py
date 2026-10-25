"""
Cloudflare Workers AI adapter for Subtitle Translation (@cf/meta/llama-3.1-8b-instruct).
Features:
- Multi-account pool with automatic failover across configured accounts.
- Chunked translation (80 cues per batch) with exact cue ID matching.
- Active account memory across files.
- Resilient error handling (401/403 credentials validation vs 429 quota rotation).
"""

from __future__ import annotations
import json
import logging
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
CHUNK_SIZE = 80  # Safe token budget for Llama 3.1 8B Instruct


class CloudflareTranslationProvider(BaseTranslationProvider):
    """Machine Translation using Cloudflare Workers AI Llama 3.1 8B Instruct with multi-account pool."""

    # Static memory to retain the active working account across file translations
    _active_account_index: Optional[int] = None

    def __init__(self, model_id: str = "@cf/meta/llama-3.1-8b-instruct", api_key: Optional[str] = None, **kwargs: Any):
        super().__init__(model_id, api_key, **kwargs)
        self.account_id = kwargs.get("account_id") or CredentialManager.get_credential("cloudflare", "account_id")

    def get_info(self) -> ProviderInfo:
        for p in VERIFIED_TRANSLATION_PROVIDERS:
            if p.provider_id == "cloudflare" and p.model_id == self.model_id:
                return p
        return ProviderInfo(
            provider_id="cloudflare",
            display_name="Cloudflare Workers AI",
            model_id=self.model_id,
            model_display_name="Llama 3.1 8B Instruct (@cf/meta/llama-3.1-8b-instruct)",
            pipeline="TRANSLATION",
            is_free=True,
            pricing_desc="10,000 Neurons/day free; $0.011 / 1k Neurons paid",
            free_tier_desc="10k free daily Neurons on Cloudflare",
            supports_timestamps=True,
            max_duration_sec=0,
            requires_key=True,
            doc_url="https://developers.cloudflare.com/workers-ai/models/llama-3.1-8b-instruct/",
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

                logger.info(f"Sending translation request to Cloudflare (Account #{idx})...")

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
                elif resp.status_code in (400, 401, 403):
                    logger.error(f"Cloudflare Account #{idx} rejected with HTTP {resp.status_code} (Invalid token/account).")
                    invalid_accounts.add(idx)
                    continue

                # 3. Rate Limit / Quota Exceeded -> rotate to next account
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

        prompt = (
            f"You are an expert film subtitle translator specializing in translation into {target_desc}.\n"
            f"Translate the following subtitle dialogue lines into natural, fluent {target_desc}.\n\n"
            "STRICT RULES:\n"
            "1. Output valid SRT format with the EXACT SAME cue numbers and timestamps.\n"
            f"2. Translate ONLY the spoken dialogue into {target_desc}.\n"
            "3. PRESERVE all formatting tags (such as <i>, </i>, <b>, </b>, {{\\an8}}), speaker dashes (- ), and musical notes (♪).\n"
            f"4. You must output ALL {len(cues_chunk)} cues without omitting any cue numbers.\n"
            "5. Output only valid SRT subtitles. No explanations, markdown tags, or introductory remarks.\n\n"
            f"--- BEGIN SUBTITLES ---\n"
            f"{chunk_srt}\n"
            f"--- END SUBTITLES ---"
        )

        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": f"You are a professional film subtitle translator. You output only valid SRT subtitle text translated into {target_desc} with exact original cue indices and timestamps."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 8192
        }

        # Attempt translation with retry on missing cue count
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                raise RuntimeError("Operation cancelled by user.")

            result = self._execute_with_account_pool(payload, cancel_token=cancel_token)
            raw_text = result.get("response", "").strip()

            if raw_text.startswith("```srt"):
                raw_text = raw_text[6:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            parsed = SRTParser.parse_text(raw_text.strip(), default_language=target_language)

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
                    translated_chunk.append(SubtitleCue(
                        index=orig.index,
                        start_ms=orig.start_ms,
                        end_ms=orig.end_ms,
                        text=trans_text
                    ))
                else:
                    missing_count += 1

            if missing_count == 0 and len(translated_chunk) == len(cues_chunk):
                return translated_chunk

            logger.warning(
                f"Cloudflare chunk attempt #{attempt}: received {len(parsed.cues)} cues, "
                f"expected {len(cues_chunk)} ({missing_count} missing). Retrying chunk..."
            )

        # If retry still failed to return all cues, fail clearly instead of silently falling back to English!
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
        chunks = [
            subtitle_file.cues[i:i + CHUNK_SIZE]
            for i in range(0, total_cues, CHUNK_SIZE)
        ]

        target_desc = LANG_NAME_MAP.get(target_language.lower(), target_language)
        logger.info(
            f"Translating {total_cues} cues to {target_desc} in {len(chunks)} chunk(s) via Cloudflare Llama 3.1..."
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

        return SubtitleFile(cues=all_translated_cues, language=target_language)
