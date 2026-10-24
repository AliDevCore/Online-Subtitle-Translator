"""
Pipeline: Machine Translation service for Subtitle (.srt) files.
Translates SRT files into target languages (Persian, Arabic, Spanish, etc.)
while strictly preserving cue timing, sequence numbering, and formatting.
"""

from __future__ import annotations
import logging
import uuid
from pathlib import Path
from typing import Optional, Callable, Any

from app.core.database import Database
from app.core.srt_parser import SRTParser
from app.core.types import SubtitleFile, JobStatus
from app.providers import get_translation_provider

logger = logging.getLogger("OnlineSub.TranslationService")


class TranslationService:
    """Manages independent subtitle translation into target languages."""

    def __init__(self, database: Optional[Database] = None):
        self.db = database or Database()

    @staticmethod
    def get_default_translated_path(srt_path: Path | str, target_lang: str = "fa") -> Path:
        """Derive translated SRT path beside source SRT."""
        p = Path(srt_path)
        name = p.name
        # If filename ends in .en.srt, change to .{target_lang}.srt
        if name.endswith(".en.srt"):
            target_name = name[:-7] + f".{target_lang}.srt"
        elif name.endswith(".srt"):
            target_name = name[:-4] + f".{target_lang}.srt"
        else:
            target_name = f"{name}.{target_lang}.srt"

        candidate = p.parent / target_name
        if not candidate.exists():
            return candidate

        # Collision-safe naming
        counter = 1
        stem = candidate.stem[:-len(target_lang)-1] if candidate.stem.endswith(f".{target_lang}") else candidate.stem
        while candidate.exists():
            candidate = p.parent / f"{stem}_{counter}.{target_lang}.srt"
            counter += 1
        return candidate

    def translate_srt(
        self,
        english_srt_path: Path | str,
        provider_id: str,
        model_id: str,
        target_lang: str = "fa",
        output_path: Optional[Path | str] = None,
        job_id: Optional[str] = None,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        cancel_token: Optional[Any] = None
    ) -> Path:
        """
        Execute independent translation workflow on an existing SRT file.
        Returns final path of validated translated SRT file.
        """
        srt_file = Path(english_srt_path)
        if not srt_file.exists():
            raise FileNotFoundError(f"SRT file not found: {srt_file}")

        job_id = job_id or uuid.uuid4().hex[:12]
        if output_path is None:
            output_path = self.get_default_translated_path(srt_file, target_lang)
        out_path = Path(output_path)

        def report(stage: str, percent: int):
            logger.info(f"[{percent}%] {stage}")
            if progress_callback:
                progress_callback(stage, percent)

        # 1. Parse existing SRT file
        report(f"Parsing SRT file: {srt_file.name}...", 10)
        source_sub = SRTParser.parse_file(srt_file)
        if not source_sub.cues:
            raise ValueError(f"No subtitle cues found in {srt_file.name}")

        report(f"Loaded {len(source_sub.cues)} subtitle cues.", 20)

        # Register translation job in database
        first_cue_st = source_sub.cues[0].start_ms / 1000.0
        last_cue_end = source_sub.cues[-1].end_ms / 1000.0

        self.db.create_job(
            job_id=job_id,
            video_path=str(srt_file),
            pipeline="TRANSLATION",
            start_seconds=first_cue_st,
            end_seconds=last_cue_end,
            translation_provider=provider_id,
            translation_model=model_id,
            output_srt_path=str(out_path)
        )
        self.db.update_job_status(job_id, JobStatus.TRANSLATING)

        # 2. Instantiate translation provider
        provider = get_translation_provider(provider_id=provider_id, model_id=model_id)

        report(f"Translating to {target_lang.upper()} with {provider.get_info().display_name}...", 40)
        translated_sub = provider.translate(
            subtitle_file=source_sub,
            target_language=target_lang,
            cancel_token=cancel_token
        )

        # 3. Validate translated SRT
        report(f"Validating translated {target_lang.upper()} subtitles...", 85)
        issues = SRTParser.validate_cues(translated_sub.cues)
        if issues:
            logger.warning(f"Translation validation notes: {'; '.join(issues)}")

        # 4. Save to disk with UTF-8
        report(f"Saving translated SRT to {out_path.name}...", 95)
        SRTParser.write_file(translated_sub, out_path, overwrite=True)

        self.db.update_job_status(job_id, JobStatus.COMPLETED, translated_srt_path=str(out_path))
        report(f"{target_lang.upper()} SRT translation completed successfully!", 100)

        return out_path
