"""
Background QThread worker for Batch Subtitle Translation.
Processes queue of subtitles sequentially with failure isolation
and real-time rate limit notifications.
"""

from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional
from PySide6.QtCore import QThread, Signal
from app.core.credential_manager import CredentialManager
from app.services.batch_service import BatchService, BatchTranslationItem


class QBatchLogHandler(logging.Handler):
    """Logging handler that captures real-time log records during batch translation and forwards them via Qt signal."""

    def __init__(self, emit_callback):
        super().__init__()
        self.emit_callback = emit_callback

    def emit(self, record: logging.LogRecord):
        try:
            # Filter to relevant application logs
            if not record.name.startswith(("OnlineSub", "OnlineSubtitleTranslator")):
                return

            time_str = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")
            msg = record.getMessage()
            msg = CredentialManager.sanitize_text(msg)

            # Omit repetitive prefixes like [INFO] [OnlineSubtitleTranslator.TranslationService]
            if record.levelno >= logging.ERROR:
                formatted = f"[{time_str}] [ERROR] {msg}"
            elif record.levelno >= logging.WARNING:
                formatted = f"[{time_str}] [WARNING] {msg}"
            else:
                formatted = f"[{time_str}] {msg}"

            self.emit_callback(formatted)
        except Exception:
            pass


class TranslationBatchWorker(QThread):
    """Worker thread running batch subtitle queue processing."""

    item_updated = Signal(str, int, int, str, int)   # (item_name, index, total, status, overall_pct)
    rate_limit_wait = Signal(str, int, int, str)     # (provider, remaining_sec, attempt, reason)
    rate_limit_cleared = Signal(str)                 # (provider)
    batch_finished = Signal(int, int, int)           # (successful_count, failed_count, cancelled_count)
    log_emitted = Signal(str)                        # (clean_log_line)
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
        handler = QBatchLogHandler(self.log_emitted.emit)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
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
            failed = sum(1 for it in items if it.status.value == "FAILED")
            cancelled = sum(1 for it in items if it.status.value in ("CANCELLED", "PENDING"))
            self.batch_finished.emit(success, failed, cancelled)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            root_logger.removeHandler(handler)
