"""
Cloudflare Workers AI adapter for Subtitle Translation (@cf/meta/llama-3.1-8b-instruct).
Features multi-account pool with automatic failover across up to 10 accounts on 429 / neuron quota exhaustion.
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

logger = logging.getLogger("OnlineSubtitleTranslator.Cloudflare")

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4/accounts"

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


class CloudflareTranslationProvider(BaseTranslationProvider):
    """Machine Translation using Cloudflare Workers AI Llama 3.1 8B Instruct with multi-account pool."""

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
        cancel_token: Optional[Any] = None
    ) -> Dict[str, Any]:
        all_accounts = [a for a in CredentialManager.get_cloudflare_accounts() if a.get("configured")]
        if not all_accounts and self.account_id and self.api_key:
            all_accounts = [{"index": 1, "account_id": self.account_id, "api_key": self.api_key, "configured": True}]

        if not all_accounts:
            raise ValueError("No valid Cloudflare accounts configured. Please add an account in Settings.")

        cycle = 0
        wait_delay = 60

        while True:
            for acct in all_accounts:
                if cancel_token and getattr(cancel_token, "is_cancelled", False):
                    raise RuntimeError("Operation cancelled by user.")

                idx = acct["index"]
                acct_id = acct["account_id"]
                token = acct["api_key"]

                url = f"{CLOUDFLARE_API_BASE}/{acct_id}/ai/run/{self.model_id}"
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }

                logger.info(f"Sending translation request to Cloudflare (Account #{idx})...")

                try:
                    resp = requests.post(url, headers=headers, json=payload, timeout=120)
                except requests.RequestException as e:
                    logger.warning(f"Network error on Cloudflare Account #{idx}: {e}")
                    continue

                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success", False) or "result" in data:
                        if cancel_token and hasattr(cancel_token, "notify_rate_limit_cleared"):
                            try:
                                cancel_token.notify_rate_limit_cleared("Cloudflare Workers AI")
                            except Exception:
                                pass
                        return data.get("result", {})
                    else:
                        errors = data.get("errors", [])
                        err_msg = "; ".join(e.get("message", "") for e in errors) if errors else "Unknown API error"
                        if "neuron" in err_msg.lower() or "limit" in err_msg.lower():
                            logger.warning(f"Cloudflare Account #{idx} quota exhausted: {err_msg}")
                            continue
                        else:
                            raise RuntimeError(f"Cloudflare error on Account #{idx}: {err_msg}")

                elif resp.status_code == 429:
                    logger.warning(f"Cloudflare Account #{idx} returned 429 Rate Limit / Quota Exceeded.")
                    continue
                else:
                    logger.warning(f"Cloudflare Account #{idx} returned HTTP {resp.status_code}: {resp.text[:200]}")
                    continue

            # If all accounts were tried and failed in this cycle
            cycle += 1
            logger.warning(
                f"All {len(all_accounts)} Cloudflare account(s) are currently rate-limited or exhausted. "
                f"Waiting {wait_delay}s before retrying..."
            )

            for rem in range(wait_delay, 0, -1):
                if cancel_token and getattr(cancel_token, "is_cancelled", False):
                    raise RuntimeError("Operation cancelled by user.")
                if cancel_token and hasattr(cancel_token, "notify_rate_limit"):
                    try:
                        cancel_token.notify_rate_limit(
                            f"All {len(all_accounts)} Cloudflare accounts exhausted. Retrying in {rem}s...",
                            rem
                        )
                    except Exception:
                        pass
                time.sleep(1.0)

            wait_delay = min(wait_delay * 2, 300)

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
            f"You are an expert film subtitle translator specializing in translation into {target_desc}.\n"
            f"Translate the following SRT subtitle into fluent, natural {target_desc} subtitle text.\n"
            "CRITICAL RULES:\n"
            "1. PRESERVE EVERY EXACT cue number and timestamp line (HH:MM:SS,mmm --> HH:MM:SS,mmm).\n"
            f"2. Translate ONLY the subtitle spoken dialogue lines into {target_desc}.\n"
            "3. Keep the exact number of cues and cue order unchanged.\n"
            "4. Output strictly valid SRT format. No markdown blocks, explanations, or notes.\n\n"
            f"{full_srt}"
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

        logger.info(f"Translating full SRT ({len(subtitle_file.cues)} cues) to {target_desc} via Cloudflare Llama 3.1...")
        result = self._execute_with_account_pool(payload, cancel_token=cancel_token)

        raw_text = result.get("response", "").strip()
        if raw_text.startswith("```srt"):
            raw_text = raw_text[6:]
        elif raw_text.startswith("```"):
            raw_text = raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]

        parsed = SRTParser.parse_text(raw_text.strip(), default_language=target_language)

        if not parsed.cues:
            raise RuntimeError(
                f"Translation failed: Cloudflare Workers AI returned no valid subtitle cues. "
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
            logger.warning(f"Cloudflare translation: expected {len(subtitle_file.cues)} cues, got {len(parsed.cues)}.")
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
