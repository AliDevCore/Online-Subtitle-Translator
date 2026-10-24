"""
Background QThread worker for Batch Subtitle Translation.
Processes queue of subtitles sequentially with failure isolation
and real-time rate limit notifications.
"""

from __future__ import annotations
from PySide6.QtCore import QThread, Signal
from app.services.batch_service import BatchService, BatchTranslationItem


class TranslationBatchWorker(QThread):
    """Worker thread running batch subtitle queue processing."""

    item_updated = Signal(str, int, int, str, int)   # (item_name, index, total, status, overall_pct)
    rate_limit_wait = Signal(str, int, int, str)     # (provider, remaining_sec, attempt, reason)
    rate_limit_cleared = Signal(str)                 # (provider)
    batch_finished = Signal(int, int)                # (successful_count, failed_count)
    failed = Signal(str)

    def __init__(
        self,
        batch_service: BatchService,
        translation_provider: str,
        translation_model: str,
        target_language: str = "fa",
        parent=None
    ):
        super().__init__(parent)
        self.batch_service = batch_service
        self.translation_provider = translation_provider
        self.translation_model = translation_model
        self.target_language = target_language
        self.is_cancelled = False

    def cancel(self):
        self.is_cancelled = True

    def notify_rate_limit(self, provider: str, remaining_sec: int, attempt: int, reason: str):
        self.rate_limit_wait.emit(provider, remaining_sec, attempt, reason)

    def notify_rate_limit_cleared(self, provider: str):
        self.rate_limit_cleared.emit(provider)

    def run(self):
        try:
            def on_item(item: BatchTranslationItem, idx: int, total: int, pct: int):
                self.item_updated.emit(item.name, idx, total, item.status.value, pct)

            items = self.batch_service.run_translation_batch(
                translation_provider=self.translation_provider,
                translation_model=self.translation_model,
                target_language=self.target_language,
                item_callback=on_item,
                cancel_token=self
            )

            success = sum(1 for it in items if it.status.value == "COMPLETED")
            failed = len(items) - success
            self.batch_finished.emit(success, failed)
        except Exception as e:
            self.failed.emit(str(e))
