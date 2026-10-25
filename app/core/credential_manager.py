"""
Secure API credential storage using Windows Credential Manager (via keyring).
Supports in-memory caching to eliminate DPAPI latency during logging and UI rendering.
Supports up to 10 Gemini accounts and up to 10 Cloudflare accounts for multi-account auto-rotation.
"""

from __future__ import annotations
import logging
import re
from typing import Optional, Dict, List, Set, Any
import keyring

logger = logging.getLogger("OnlineSubtitleTranslator.Security")

SERVICE_NAME_PREFIX = "OnlineSubtitleTranslator"


class CredentialManager:
    """Manages secure persistence, in-memory caching, and retrieval of API credentials."""

    _mem_cache: Dict[str, Optional[str]] = {}
    _cached_secrets: Set[str] = set()

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory credential cache (useful in tests)."""
        cls._mem_cache.clear()
        cls._cached_secrets.clear()

    @staticmethod
    def _service_key(provider_id: str, field_name: str = "api_key") -> str:
        return f"{SERVICE_NAME_PREFIX}_{provider_id}_{field_name}"

    @classmethod
    def get_credential(cls, provider_id: str, field_name: str = "api_key") -> Optional[str]:
        """Retrieve credential securely from Windows Credential Manager with memory caching."""
        cache_key = f"{provider_id}:{field_name}"
        if cache_key in cls._mem_cache:
            return cls._mem_cache[cache_key]

        service = cls._service_key(provider_id, field_name)
        try:
            val = keyring.get_password(service, "OnlineSubUser")
            if not val:
                # Fallback to legacy OnlineSub prefix for backwards compatibility
                legacy_service = f"OnlineSub_{provider_id}_{field_name}"
                val = keyring.get_password(legacy_service, "OnlineSubUser")

            res = val if val else None
            cls._mem_cache[cache_key] = res
            if res and len(res.strip()) > 5:
                cls._cached_secrets.add(res.strip())
            return res
        except Exception as e:
            logger.warning(f"Failed to read credential for {provider_id}/{field_name}: {e}")
            cls._mem_cache[cache_key] = None
            return None

    @classmethod
    def set_credential(cls, provider_id: str, secret_value: str, field_name: str = "api_key") -> bool:
        """Store credential securely in Windows Credential Manager and update memory cache."""
        cache_key = f"{provider_id}:{field_name}"
        service = cls._service_key(provider_id, field_name)
        try:
            if not secret_value or not secret_value.strip():
                return cls.delete_credential(provider_id, field_name)

            clean_val = secret_value.strip()
            keyring.set_password(service, "OnlineSubUser", clean_val)
            cls._mem_cache[cache_key] = clean_val
            if len(clean_val) > 5:
                cls._cached_secrets.add(clean_val)
            logger.info(f"Credential updated for {provider_id}/{field_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to store credential for {provider_id}/{field_name}: {e}")
            return False

    @classmethod
    def delete_credential(cls, provider_id: str, field_name: str = "api_key") -> bool:
        """Remove credential from Windows Credential Manager and purge from cache."""
        cache_key = f"{provider_id}:{field_name}"
        service = cls._service_key(provider_id, field_name)
        old_val = cls._mem_cache.pop(cache_key, None)
        if old_val and old_val in cls._cached_secrets:
            cls._cached_secrets.discard(old_val)

        try:
            keyring.delete_password(service, "OnlineSubUser")
            logger.info(f"Credential removed for {provider_id}/{field_name}")
            return True
        except keyring.errors.PasswordDeleteError:
            return True
        except Exception as e:
            logger.warning(f"Failed to delete credential for {provider_id}/{field_name}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Gemini Multi-Account Pool (Up to 10 Accounts)
    # -------------------------------------------------------------------------
    @classmethod
    def get_gemini_accounts(cls, max_accounts: int = 10) -> List[Dict[str, Any]]:
        accounts = []
        for idx in range(1, max_accounts + 1):
            if idx == 1:
                key = cls.get_credential("gemini", "api_key_1") or cls.get_credential("gemini", "api_key")
            else:
                key = cls.get_credential("gemini", f"api_key_{idx}")

            is_configured = bool(key and len(key.strip()) > 8)
            accounts.append({
                "index": idx,
                "api_key": (key or "").strip(),
                "configured": is_configured
            })
        return accounts

    @classmethod
    def set_gemini_account(cls, index: int, api_key: str) -> bool:
        if index < 1 or index > 10:
            return False
        cls.set_credential("gemini", api_key, f"api_key_{index}")
        if index == 1:
            cls.set_credential("gemini", api_key, "api_key")
        return True

    @classmethod
    def delete_gemini_account(cls, index: int) -> bool:
        cls.delete_credential("gemini", f"api_key_{index}")
        if index == 1:
            cls.delete_credential("gemini", "api_key")
        return True

    # -------------------------------------------------------------------------
    # Cloudflare Multi-Account Pool (Up to 10 Accounts)
    # -------------------------------------------------------------------------
    @classmethod
    def get_cloudflare_accounts(cls, max_accounts: int = 10) -> List[Dict[str, Any]]:
        accounts = []
        for idx in range(1, max_accounts + 1):
            if idx == 1:
                acct = cls.get_credential("cloudflare", "account_id_1") or cls.get_credential("cloudflare", "account_id")
                key = cls.get_credential("cloudflare", "api_key_1") or cls.get_credential("cloudflare", "api_key")
            else:
                acct = cls.get_credential("cloudflare", f"account_id_{idx}")
                key = cls.get_credential("cloudflare", f"api_key_{idx}")

            is_configured = bool(acct and key and len(acct.strip()) > 5 and len(key.strip()) > 5)
            accounts.append({
                "index": idx,
                "account_id": (acct or "").strip(),
                "api_key": (key or "").strip(),
                "configured": is_configured
            })
        return accounts

    @classmethod
    def set_cloudflare_account(cls, index: int, account_id: str, api_key: str) -> bool:
        if index < 1 or index > 10:
            return False
        cls.set_credential("cloudflare", account_id, f"account_id_{index}")
        cls.set_credential("cloudflare", api_key, f"api_key_{index}")
        if index == 1:
            cls.set_credential("cloudflare", account_id, "account_id")
            cls.set_credential("cloudflare", api_key, "api_key")
        return True

    @classmethod
    def delete_cloudflare_account(cls, index: int) -> bool:
        cls.delete_credential("cloudflare", f"account_id_{index}")
        cls.delete_credential("cloudflare", f"api_key_{index}")
        if index == 1:
            cls.delete_credential("cloudflare", "account_id")
            cls.delete_credential("cloudflare", "api_key")
        return True

    @classmethod
    def mask_key(cls, key: Optional[str]) -> str:
        """Return masked representation of a secret (e.g. AIzaSy...ABCD or (Not Set))."""
        if not key or len(key.strip()) == 0:
            return "(Not configured)"
        stripped = key.strip()
        if len(stripped) <= 8:
            return "********"
        return f"{stripped[:4]}...{stripped[-4:]}"

    @classmethod
    def sanitize_text(cls, text: str, known_secrets: Optional[list[str]] = None) -> str:
        """
        Redact sensitive keys from strings, URLs, and log messages using cached secrets and regex.
        Never calls keyring or DPAPI in the logging hot path.
        """
        if not text:
            return ""
        sanitized = text

        # 1. Redact explicitly passed secrets
        if known_secrets:
            for s in known_secrets:
                if s and len(s) > 4:
                    sanitized = sanitized.replace(s, "[REDACTED_API_KEY]")

        # 2. Redact cached secrets without hitting DPAPI
        for secret in cls._cached_secrets:
            if len(secret) > 8:
                redacted = f"{secret[:4]}...{secret[-4:]}"
                sanitized = sanitized.replace(secret, redacted)

        # 3. Regex patterns for API keys and tokens in URLs/Headers
        sanitized = re.sub(r'(key=)[^&\s]+', r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r'(Bearer\s+)[a-zA-Z0-9_\-\.]{10,}', r'\1[REDACTED]', sanitized, flags=re.IGNORECASE)
        sanitized = re.sub(r'(AIzaSy)[A-Za-z0-9_-]{33}', r'\1...[REDACTED]', sanitized)
        return sanitized
