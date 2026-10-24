"""
Background QThread worker for Translation.
Translates SRT files asynchronously without blocking the UI.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from PySide6.QtCore import QThread, Signal

from app.services.translation_service import TranslationService


class TranslationWorker(QThread):
    """Worker thread executing subtitle translation into a target language."""

    progress = Signal(str, int)       # (stage_description, percentage)
    rate_limit_wait = Signal(str, int, int, str)     # (provider, remaining_sec, attempt, reason)
    rate_limit_cleared = Signal(str)                 # (provider)
    finished = Signal(str)            # (translated_srt_path)
    failed = Signal(str)              # (error_message)

    def __init__(
        self,
        translation_service: TranslationService,
        english_srt_path: Path | str,
        provider_id: str,
        model_id: str,
        target_lang: str = "fa",
        output_path: Optional[Path | str] = None,
        parent=None
    ):
        super().__init__(parent)
        self.translation_service = translation_service
        self.english_srt_path = english_srt_path
        self.provider_id = provider_id
        self.model_id = model_id
        self.target_lang = target_lang
        self.output_path = output_path
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def notify_rate_limit(self, provider: str, remaining_sec: int, attempt: int, reason: str):
        self.rate_limit_wait.emit(provider, remaining_sec, attempt, reason)

    def notify_rate_limit_cleared(self, provider: str):
        self.rate_limit_cleared.emit(provider)

    def run(self):
        try:
            out_file = self.translation_service.translate_srt(
                english_srt_path=self.english_srt_path,
                provider_id=self.provider_id,
                model_id=self.model_id,
                target_lang=self.target_lang,
                output_path=self.output_path,
                progress_callback=lambda stage, p: self.progress.emit(stage, p),
                cancel_token=self
            )
            if self.is_cancelled:
                self.failed.emit("Operation cancelled by user.")
            else:
                self.finished.emit(str(out_file))
        except Exception as e:
            self.failed.emit(str(e))
