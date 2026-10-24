"""
Batch processing service for handling multiple subtitle files in Online Subtitle Translator.
Ensures failure isolation, queue management, and resumable execution.
"""

from __future__ import annotations
import logging
import uuid
from pathlib import Path
from typing import List, Optional, Callable, Any

from app.core.database import Database
from app.core.types import JobStatus
from app.core.srt_parser import SRTParser
from app.services.translation_service import TranslationService

logger = logging.getLogger("OnlineSubtitleTranslator.BatchService")

SUBTITLE_EXTENSIONS = {".srt"}


class BatchTranslationItem:
    """Represents an SRT file job item in the translation batch queue."""

    def __init__(
        self,
        srt_path: Path | str,
        target_language: str = "fa"
    ):
        self.item_id = uuid.uuid4().hex[:8]
        self.srt_path = Path(srt_path)
        self.target_language = target_language
        self.status: JobStatus = JobStatus.PENDING
        self.cues_count: int = 0
        self.file_size_kb: float = 0.0
        self.error_msg: Optional[str] = None
        self.generated_srt: Optional[Path] = None

        if self.srt_path.exists():
            try:
                self.file_size_kb = self.srt_path.stat().st_size / 1024.0
            except Exception:
                pass

    @property
    def name(self) -> str:
        return self.srt_path.name


# Backwards compatibility alias
BatchItem = BatchTranslationItem


class BatchService:
    """Processes queues of subtitle files with failure isolation."""

    def __init__(
        self,
        translation_service: Optional[TranslationService] = None,
        database: Optional[Database] = None
    ):
        self.translator = translation_service or TranslationService()
        self.db = database or Database()
        self.translation_queue: List[BatchTranslationItem] = []

    @property
    def queue(self) -> List[BatchTranslationItem]:
        return self.translation_queue

    @queue.setter
    def queue(self, value: List[BatchTranslationItem]):
        self.translation_queue = value

    def add_translation_item(self, item: BatchTranslationItem) -> None:
        """Add subtitle item to the translation queue."""
        self.translation_queue.append(item)

    def add_item(self, item: BatchTranslationItem) -> None:
        """Alias for add_translation_item."""
        self.add_translation_item(item)

    def clear(self) -> None:
        self.translation_queue.clear()

    def clear_translations(self) -> None:
        self.translation_queue.clear()

    def scan_srt_folder(
        self,
        folder_path: Path | str,
        target_language: str = "fa"
    ) -> List[BatchTranslationItem]:
        """Scan a directory for SRT files, ignoring already translated .{target_lang}.srt files."""
        folder = Path(folder_path)
        if not folder.exists() or not folder.is_dir():
            return []

        found_items: List[BatchTranslationItem] = []
        candidates = sorted(
            [
                p for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() == ".srt" and not p.name.endswith(f".{target_language}.srt")
            ],
            key=lambda x: x.name.lower()
        )

        for p in candidates:
            item = BatchTranslationItem(srt_path=p, target_language=target_language)
            try:
                sub = SRTParser.parse_file(p)
                item.cues_count = len(sub.cues)
            except Exception:
                pass
            found_items.append(item)

        return found_items

    def run_translation_batch(
        self,
        translation_provider: str,
        translation_model: str,
        target_language: str = "fa",
        item_callback: Optional[Callable[[BatchTranslationItem, int, int, int], None]] = None,
        cancel_token: Optional[Any] = None
    ) -> List[BatchTranslationItem]:
        """Process all subtitle items sequentially with failure isolation and granular progress."""
        total = len(self.translation_queue)
        logger.info(f"Starting Subtitle Translation batch of {total} items...")

        for idx, item in enumerate(self.translation_queue, 1):
            if cancel_token and getattr(cancel_token, "is_cancelled", False):
                logger.info("Translation batch execution cancelled by user.")
                item.status = JobStatus.CANCELLED
                break

            if item.status == JobStatus.COMPLETED:
                continue

            item.status = JobStatus.TRANSLATING
            base_pct = int(((idx - 1) / max(total, 1)) * 100)
            if item_callback:
                item_callback(item, idx, total, base_pct)

            def sub_progress(stage: str, p: int):
                fraction = p / 100.0
                overall = int((((idx - 1) + fraction) / max(total, 1)) * 100)
                if item_callback:
                    item_callback(item, idx, total, overall)

            try:
                target_lang = getattr(item, "target_language", target_language) or target_language
                out_srt = self.translator.translate_srt(
                    english_srt_path=item.srt_path,
                    provider_id=translation_provider,
                    model_id=translation_model,
                    target_lang=target_lang,
                    progress_callback=sub_progress,
                    cancel_token=cancel_token
                )
                item.generated_srt = out_srt
                item.status = JobStatus.COMPLETED

            except Exception as e:
                logger.error(f"Failed to translate batch subtitle item {item.srt_path.name}: {e}")
                item.status = JobStatus.FAILED
                item.error_msg = str(e)

            done_pct = int((idx / max(total, 1)) * 100)
            if item_callback:
                item_callback(item, idx, total, done_pct)

        return self.translation_queue

    # Backwards compatibility alias
    run_batch = run_translation_batch
