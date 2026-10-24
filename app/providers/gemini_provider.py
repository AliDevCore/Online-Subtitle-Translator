"""
Google Gemini provider adapter for Subtitle Translation.
Features 2-layer automatic rotation:
1. Model rotation across candidate Flash models (3.5, 3.8, etc.)
2. Multi-account pool rotation across up to 10 separate Gemini API keys
3. Arbitrary target language support (Persian, Arabic, Spanish, etc.)
4. Comprehensive safety settings to prevent content filter blockage on adult/cinematic dialogues.
"""

from __future__ import annotations
import json
import logging
import time
from typing import Optional, Tuple, Any, List, Dict
import requests

from app.core.config import VERIFIED_TRANSLATION_PROVIDERS
from app.core.credential_manager import CredentialManager
from app.core.srt_parser import SRTParser
from app.core.types import SubtitleFile, SubtitleCue, ProviderInfo
from app.providers.base import BaseTranslationProvider

logger = logging.getLogger("OnlineSubtitleTranslator.Gemini")

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"

GEMINI_FLASH_ROTATION_POOL: List[str] = [
    "gemini-3-flash-preview",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
]

LANG_NAME_MAP = {
    "fa": "natural Persian (فارسی)",
    "ar": "fluent Arabic (العربية)",
    "es": "fluent Spanish (Español)",
    "fr": "fluent French (Français)",
    "de": "fluent German (Deutsch)",
    "it": "fluent Italian (Italiano)",
    "tr": "fluent Turkish (Türkçe)",
    "ru": "fluent Russian (Русский)",
    "zh": "fluent Chinese (中文)",
    "ja": "fluent Japanese (日本語)",
    "ko": "fluent Korean (한국어)",
    "ku": "fluent Kurdish (کوردی)",
    "hi": "fluent Hindi (हिन्दी)",
    "ur": "fluent Urdu (اردو)",
    "pt": "fluent Portuguese (Português)",
    "nl": "fluent Dutch (Nederlands)",
}


def _request_with_gemini_pool(
    payload: dict,
    headers: dict,
    starting_model: str,
    cancel_token: Optional[Any] = None,
    max_cycles: int = 999999
) -> Tuple[dict, str]:
    """
    Execute request to Gemini API with 2-layer rotation:
    1. Tests models in pool on the current account.
    2. If all models on that account return 429 or safety block, switches to the next configured Gemini account.
    3. If all accounts and all models are exhausted, enters countdown wait.
    Returns (response_data, successful_model_id).
    """
    all_accounts = [a for a in CredentialManager.get_gemini_accounts() if a.get("configured")]
    if not all_accounts:
        key = CredentialManager.get_credential("gemini", "api_key")
        if key:
            all_accounts = [{"index": 1, "api_key": key, "configured": True}]

    if not all_accounts:
        raise ValueError("No valid Google Gemini API keys configured. Please add an API key in Settings.")

    candidates = [starting_model]
    for m in GEMINI_FLASH_ROTATION_POOL:
        if m not in candidates:
            candidates.append(m)

    cycle = 0
    current_wait_delay = 60

    while cycle < max_cycles:
        if cancel_token and getattr(cancel_token, "is_cancelled", False):
            raise RuntimeError("Operation cancelled by user.")

        # Iterate through all configured accounts
        for acct in all_accounts:
            acct_idx = acct["index"]
            api_key = acct["api_key"]

            # Try candidate models for this account
            for model_idx, model in enumerate(candidates):
                if cancel_token and getattr(cancel_token, "is_cancelled", False):
                    raise RuntimeError("Operation cancelled by user.")

                url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={api_key}"
                try:
                    resp = requests.post(url, json=payload, headers=headers, timeout=120)

                    if resp.status_code == 200:
                        data = resp.json()
                        candidates_list = data.get("candidates", [])
                        if candidates_list:
                            candidate = candidates_list[0]
                            finish_reason = candidate.get("finishReason", "")
                            if finish_reason == "SAFETY":
                                logger.warning(
                                    f"Gemini Account #{acct_idx} model '{model}' response was blocked by SAFETY filter. "
                                    "Rotating to next model..."
                                )
                                continue

                            parts = candidate.get("content", {}).get("parts", [])
                            if parts and any("text" in p for p in parts):
                                if cancel_token and hasattr(cancel_token, "notify_rate_limit_cleared"):
                                    try:
                                        cancel_token.notify_rate_limit_cleared("Google Gemini API")
                                    except Exception:
                                        pass
                                return data, model

                    is_rate_limited = (resp.status_code in (429, 503, 404))
                    resp_lower = resp.text.lower()
                    if not is_rate_limited and ("rate limit" in resp_lower or "quota" in resp_lower or "resource_exhausted" in resp_lower):
                        is_rate_limited = True

                    if is_rate_limited:
                        next_model = candidates[(model_idx + 1) % len(candidates)]
                        logger.warning(
                            f"Gemini Account #{acct_idx} model '{model}' rate-limited ({resp.status_code}). "
                            f"Rotating to model '{next_model}'..."
                        )
                        continue

                    # If authentication or other fatal error on this account
                    logger.warning(f"Gemini Account #{acct_idx} error ({resp.status_code}): {resp.text[:200]}")
                    break  # Move to next account

                except requests.exceptions.RequestException as e:
                    logger.warning(f"Network error on Gemini Account #{acct_idx} (model {model}): {e}")
                    continue

        # If all candidate models across all accounts returned 429
        cycle += 1
        logger.warning(
            f"All {len(all_accounts)} Gemini account(s) and their models are temporarily rate-limited. "
            f"Waiting {current_wait_delay}s before retrying pool..."
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
                except Exception:
                    pass

            time.sleep(1)

        current_wait_delay = min(current_wait_delay * 2, 300)

    raise RuntimeError("Gemini translation failed after exhausting all retry cycles.")


class GeminiTranslationProvider(BaseTranslationProvider):
    """Machine Translation using Google Gemini Flash models with multi-account pool."""

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

        full_srt = subtitle_file.to_srt()
        target_desc = LANG_NAME_MAP.get(target_language.lower(), target_language)

        prompt = (
            f"You are an expert film subtitle translator and linguist specializing in translation into {target_desc}.\n"
            f"Translate the following SRT subtitle dialogue lines into fluent, natural {target_desc} subtitle text.\n"
            "CRITICAL RULES:\n"
            "1. PRESERVE EVERY EXACT cue number and timestamp line (HH:MM:SS,mmm --> HH:MM:SS,mmm).\n"
            f"2. Translate ONLY the subtitle spoken dialogue lines into {target_desc}.\n"
            "3. Keep the exact number of cues and cue order unchanged.\n"
            "4. Output strictly valid SRT format. No markdown blocks, explanations, or notes.\n\n"
            f"{full_srt}"
        )

        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 65536
            },
            # Disable safety filters so adult/cinematic dialogues are not blocked
            "safetySettings": [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "BLOCK_NONE"},
            ]
        }

        logger.info(f"Translating full SRT ({len(subtitle_file.cues)} cues) to {target_desc} via Gemini ({self.model_id}) with multi-account pool...")
        data, used_model = _request_with_gemini_pool(
            payload=payload,
            headers=headers,
            starting_model=self.model_id,
            cancel_token=cancel_token
        )

        if used_model != self.model_id:
            logger.info(f"Gemini translation completed using auto-rotated model '{used_model}' (switched from '{self.model_id}').")
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

        if not parsed.cues:
            raise RuntimeError(
                f"Translation failed: Google Gemini returned no valid subtitle cues. "
                f"Model response was: {raw_text[:200]}"
            )

        translated_cues: List[SubtitleCue] = []
        if len(parsed.cues) == len(subtitle_file.cues):
            for orig, trans in zip(subtitle_file.cues, parsed.cues):
                translated_cues.append(SubtitleCue(
                    index=orig.index,
                    start_ms=orig.start_ms,
                    end_ms=orig.end_ms,
                    text=trans.text.strip()
                ))
        else:
            logger.warning(f"Gemini translation: expected {len(subtitle_file.cues)} cues, got {len(parsed.cues)}.")
            for i, orig in enumerate(subtitle_file.cues):
                if i < len(parsed.cues):
                    translated_cues.append(SubtitleCue(
                        index=orig.index,
                        start_ms=orig.start_ms,
                        end_ms=orig.end_ms,
                        text=parsed.cues[i].text.strip()
                    ))
                else:
                    translated_cues.append(orig)

        return SubtitleFile(cues=translated_cues, language=target_language)
