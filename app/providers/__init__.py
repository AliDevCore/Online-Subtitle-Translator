"""
Provider factory and registry for Online Subtitle Translator.
"""

from __future__ import annotations
from typing import Optional, Any
from app.core.credential_manager import CredentialManager
from app.providers.base import BaseTranslationProvider
from app.providers.gemini_provider import GeminiTranslationProvider
from app.providers.cloudflare_provider import CloudflareTranslationProvider


def get_translation_provider(
    provider_id: str,
    model_id: str,
    api_key: Optional[str] = None,
    **kwargs: Any
) -> BaseTranslationProvider:
    """Instantiate the requested Translation provider adapter with secure credentials."""
    if not api_key:
        api_key = CredentialManager.get_credential(provider_id)

    if provider_id == "gemini":
        return GeminiTranslationProvider(model_id=model_id, api_key=api_key, **kwargs)
    elif provider_id == "cloudflare":
        return CloudflareTranslationProvider(model_id=model_id, api_key=api_key, **kwargs)
    else:
        raise ValueError(f"Unknown translation provider: {provider_id}")
