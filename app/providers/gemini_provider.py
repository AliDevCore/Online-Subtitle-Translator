"""
Google Gemini provider adapter for Subtitle Translation.
Features:
- 2-layer automatic rotation: model pool failover and multi-account pool rotation.
- API key passed securely via 'x-goog-api-key' HTTP header (never exposed in URL query string).
- Chunked translation (80 cues per batch) with exact cue ID matching.
- Active account memory across files.
- Resilient error handling (400/401/403 credentials validation vs 429 quota rotation vs 404 model retirement).
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

logger = logging.getLogger("OnlineSubtitleTranslator.Gemini")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
CHUNK_SIZE = 150  # 150 cues per chunk as requested by user

GEMINI_FLASH_ROTATION_POOL: List[str] = [
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
]


def _request_with_gemini_pool(
    payload: dict,
    starting_model: str,
    cancel_token: Optional[Any] = None,
    max_cycles: int = 5,
    api_key: Optional[str] = None
) -> Tuple[dict, str]:
    """Module-level entry point for Gemini pool request (for test compatibility)."""
    provider = GeminiTranslationProvider(model_id=starting_model, api_key=api_key)
    return provider._execute_with_pool(payload, starting_model, cancel_token, max_cycles)


class GeminiTranslationProvider(BaseTranslationProvider):
    """Machine Translation using Google Gemini Flash models with multi-account pool."""

    # Static memory to retain the active working account across file translations
    _active_account_index: Optional[int] = None

    def __init__(self, model_id: str = "gemini-3-flash-preview", api_key: Optional[str] = None, **kwargs: Any):
        super().__init__(model_id, api_key, **kwargs)

    def get_info(self) -> ProviderInfo:
        for p in VERIFIED_TRANSLATION_PROVIDERS:
            if p.provider_id == "gemini" and p.model_id == self.model_id:
                return p
        return ProviderInfo(
            provider_id="gemini",
            display_name="Google Gemini API",
            model_id=self.model_id,
            model_display_name=f"Gemini ({self.model_id})",
            pipeline="TRANSLATION",
            is_free=True,
            pricing_desc="Free tier on Google AI Studio",
            free_tier_desc="High quality translation with multi-model auto rotation",
            supports_timestamps=True,
            max_duration_sec=0,
            requires_key=True,
            doc_url="https://ai.google.dev/gemini-api/docs",
            verification_date="2026-10"
        )

    def validate_credentials(self) -> Tuple[bool, str]:
        if self.api_key and len(self.api_key.strip()) >= 10:
            return True, "API Key format verified."
        accounts = [a for a in CredentialManager.get_gemini_accounts() if a.get("configured")]
        if not accounts:
            return False, "Google Gemini API Key is missing or invalid."
        return True, "API Key format verified."

    def _execute_with_pool(
        self,
        payload: dict,
        starting_model: str,
        cancel_token: Optional[Any] = None,
        max_cycles: int = 5
    ) -> Tuple[dict, str]:
        """
        Execute request to Gemini API with 2-layer rotation:
        1. Tests models in pool on the current account.
        2. If all models on that account return 429, switches to next Gemini account.
        3. If all accounts and all models are exhausted, enters countdown wait up to max_cycles.
        """
        if self.api_key:
            all_accounts = [{"index": 1, "api_key": self.api_key, "configured": True}]
        else:
            all_accounts = [a for a in CredentialManager.get_gemini_accounts() if a.get("configured")]
            if not all_accounts:
                key = CredentialManager.get_credential("gemini", "api_key")
                if key:
                    all_accounts = [{"index": 1, "api_key": key, "configured": True}]

        if not all_accounts:
            raise ValueError("No valid Google Gemini API keys configured. Please add an API key in Settings.")

        # Reorder accounts so that the last known working account is tried first
        if self._active_account_index is not None:
            active = [a for a in all_accounts if a["index"] == self._active_account_index]
            others = [a for a in all_accounts if a["index"] != self._active_account_index]
            ordered_accounts = active + others
        else:
            ordered_accounts = list(all_accounts)

        candidates = [starting_model]
        for m in GEMINI_FLASH_ROTATION_POOL:
            if m not in candidates:
                candidates.append(m)

        invalid_accounts: Set[int] = set()
        deprecated_models: Set[str] = set()
        cycle = 0
        current_wait_delay = 45

        while cycle < max_cycles:
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                raise RuntimeError("Operation cancelled by user.")

            active_model_pool = [m for m in candidates if m not in deprecated_models]
            if not active_model_pool:
                active_model_pool = candidates[:1]

            valid_tried = 0
            for acct in ordered_accounts:
                acct_idx = acct["index"]
                if acct_idx in invalid_accounts:
                    continue

                valid_tried += 1
                api_key = acct["api_key"]

                # Pass API key strictly in HTTP header
                headers = {
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key
                }

                # Try candidate models for this account
                for model_idx, model in enumerate(active_model_pool):
                    if cancel_token and getattr(cancel_token, "is_cancelled", False):
                        raise RuntimeError("Operation cancelled by user.")

                    url = f"{GEMINI_API_BASE}/models/{model}:generateContent"
                    try:
                        resp = requests.post(url, json=payload, headers=headers, timeout=90)

                        if resp.status_code == 200:
                            data = resp.json()
                            candidates_list = data.get("candidates", [])
                            if candidates_list:
                                candidate = candidates_list[0]
                                finish_reason = candidate.get("finishReason", "")
                                if finish_reason == "SAFETY":
                                    logger.warning(
                                        f"Gemini Account #{acct_idx} model '{model}' response blocked by SAFETY filter. "
                                        "Rotating to next model..."
                                    )
                                    continue

                                parts = candidate.get("content", {}).get("parts", [])
                                if parts and any("text" in p for p in parts):
                                    GeminiTranslationProvider._active_account_index = acct_idx
                                    if cancel_token and hasattr(cancel_token, "notify_rate_limit_cleared"):
                                        try:
                                            cancel_token.notify_rate_limit_cleared("Google Gemini API")
                                        except Exception as ex:
                                            logger.debug(f"Signal notification error: {ex}")
                                    return data, model

                        # 404: Model not found or discontinued -> retire model
                        if resp.status_code == 404:
                            logger.warning(f"Gemini model '{model}' returned HTTP 404. Retiring from candidate pool.")
                            deprecated_models.add(model)
                            continue

                        # 400, 401, 403: Invalid API key -> mark account invalid and skip
                        if resp.status_code in (400, 401, 403):
                            resp_err = resp.text.lower()
                            if "key" in resp_err or "auth" in resp_err or "unauthorized" in resp_err:
                                logger.error(f"Gemini Account #{acct_idx} invalid API key (HTTP {resp.status_code}).")
                                invalid_accounts.add(acct_idx)
                                break  # Break to next account

                        # Rate Limit / Quota Check
                        is_rate_limited = (resp.status_code in (429, 503))
                        resp_lower = resp.text.lower()
                        if not is_rate_limited and ("rate limit" in resp_lower or "quota" in resp_lower or "resource_exhausted" in resp_lower):
                            is_rate_limited = True

                        if is_rate_limited:
                            next_model = active_model_pool[(model_idx + 1) % len(active_model_pool)]
                            logger.warning(
                                f"Gemini Account #{acct_idx} model '{model}' rate-limited ({resp.status_code}). "
                                f"Rotating to model '{next_model}'..."
                            )
                            continue

                        logger.warning(f"Gemini Account #{acct_idx} error ({resp.status_code}): {resp.text[:200]}")
                        break  # Move to next account

                    except requests.exceptions.RequestException as e:
                        logger.warning(f"Network error on Gemini Account #{acct_idx} (model {model}): {e}")
                        continue

            # Check if all accounts are permanently invalid
            if len(invalid_accounts) >= len(ordered_accounts):
                raise RuntimeError(
                    f"All {len(ordered_accounts)} Google Gemini API key(s) failed authentication. "
                    "Please check your API key in Settings."
                )

            # If all candidate models across all accounts returned 429
            cycle += 1
            if cycle >= max_cycles:
                break

            logger.warning(
                f"All active Gemini account(s) are temporarily rate-limited. "
                f"Waiting {current_wait_delay}s before retrying pool (Cycle {cycle}/{max_cycles})..."
            )

            for rem in range(current_wait_delay, 0, -1):
                if cancel_token and getattr(cancel_token, "is_cancelled", False):
                    raise RuntimeError("Operation cancelled by user.")

                if cancel_token and hasattr(cancel_token, "notify_rate_limit"):
                    try:
                        cancel_token.notify_rate_limit(
                            "Google Gemini",
                            rem,
                            cycle,
                            f"All Gemini accounts quota reached. Waiting for reset ({rem}s)..."
                        )
                    except Exception as ex:
                        logger.debug(f"Signal notification error: {ex}")

                time.sleep(1)

            current_wait_delay = min(current_wait_delay * 2, 180)

        raise RuntimeError(
            f"Google Gemini translation failed after {max_cycles} retry cycles across all accounts and models."
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
            f"You are an expert film subtitle translator and linguist specializing in translation into {target_desc}.\n"
            f"Translate the following subtitle dialogue lines into fluent, natural {target_desc}.\n\n"
            "STRICT RULES:\n"
            "1. Output valid SRT format with the EXACT SAME cue numbers and timestamps.\n"
            f"2. Translate ONLY the spoken dialogue into {target_desc}.\n"
            "3. PRESERVE all formatting tags (such as <i>, </i>, <b>, </b>, {{\\an8}}), speaker dashes (- ), and musical notes (♪).\n"
            f"4. You must output ALL {len(cues_chunk)} cues without omitting any cue numbers.\n"
            "5. FRAGMENTED LINES: Even if an English cue is a single isolated word or fragment (e.g. 'What', 'And', 'If with'), you MUST output that cue number with its translation or original word. NEVER merge multiple cue numbers into one or skip any cue number!\n"
            "6. Output only valid SRT subtitles. No explanations, markdown tags, or introductory remarks.\n\n"
            f"--- BEGIN SUBTITLES ---\n"
            f"{chunk_srt}\n"
            f"--- END SUBTITLES ---"
        )

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 8192
            },
            # Allow all cinematic/dialogue content
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
            ]
        }

        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                raise RuntimeError("Operation cancelled by user.")

            data, used_model = self._execute_with_pool(
                payload=payload,
                starting_model=self.model_id,
                cancel_token=cancel_token
            )
            if used_model != self.model_id:
                self.model_id = used_model

            try:
                raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            except (KeyError, IndexError):
                raise RuntimeError("Failed to parse Gemini translation response.")

            if raw_text.startswith("```srt"):
                raw_text = raw_text[6:]
            elif raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            parsed = SRTParser.parse_text(raw_text.strip(), default_language=target_language)

            id_to_text: Dict[int, str] = {c.index: c.text.strip() for c in parsed.cues if c.text.strip()}

            translated_chunk: List[SubtitleCue] = []
            missing_count = 0
            for orig in cues_chunk:
                trans_text = id_to_text.get(orig.index)
                if not trans_text and len(parsed.cues) == len(cues_chunk):
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
                    f"Gemini chunk attempt #{attempt}: received {len(parsed.cues)} cues, "
                    f"expected {len(cues_chunk)} ({missing_count} missing). Retrying chunk..."
                )
                continue

            # On final attempt, allow small number of merged dialogue fragments (<= 15%) without halting the entire movie
            max_tolerated_missing = max(1, int(len(cues_chunk) * 0.15)) if len(cues_chunk) >= 10 else 0
            if missing_count <= max_tolerated_missing:
                logger.warning(
                    f"Gemini chunk completed with {len(cues_chunk) - missing_count}/{len(cues_chunk)} translated cues. "
                    f"{missing_count} dialogue fragment(s) merged by model were safely retained without timing shift."
                )
                return translated_chunk

            raise RuntimeError(
                f"Google Gemini translation failed for cues {expected_indices[0]} to {expected_indices[-1]}: "
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
            f"Translating {total_cues} cues to {target_desc} in {len(chunks)} chunk(s) via Gemini ({self.model_id})..."
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

            # Gentle pacing pause between chunks to stay strictly within Gemini Free Tier 15 RPM
            if chunk_idx < len(chunks):
                for _ in range(20):  # 2.0s sleep in 100ms intervals for responsive cancellation
                    if cancel_token and getattr(cancel_token, "is_cancelled", False):
                        raise RuntimeError("Operation cancelled by user.")
                    time.sleep(0.1)

        return SubtitleFile(cues=all_translated_cues, language=target_language)
