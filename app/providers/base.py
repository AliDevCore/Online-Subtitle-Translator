"""
Base abstract classes and interfaces for Translation providers.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional, Tuple, Any
from app.core.types import SubtitleFile, ProviderInfo


class BaseTranslationProvider(ABC):
    """Abstract interface for Machine Translation providers."""

    def __init__(self, model_id: str, api_key: Optional[str] = None, **kwargs: Any):
        self.model_id = model_id
        self.api_key = api_key
        self.extra_config = kwargs

    @abstractmethod
    def translate(
        self,
        subtitle_file: SubtitleFile,
        target_language: str = "fa",
        cancel_token: Optional[Any] = None
    ) -> SubtitleFile:
        """
        Translate English SubtitleFile into target language (default Persian / fa).
        MUST preserve cue numbering, timestamps, ordering, and structure.
        """
        pass

    @abstractmethod
    def validate_credentials(self) -> Tuple[bool, str]:
        """Validate API key or account prerequisites."""
        pass

    @abstractmethod
    def get_info(self) -> ProviderInfo:
        """Return provider and model metadata."""
        pass
