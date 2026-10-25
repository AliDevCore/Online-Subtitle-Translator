"""
Core data types and structures for Online Subtitle Translator.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any


class JobStatus(str, Enum):
    PENDING = "PENDING"
    TRANSLATING = "TRANSLATING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PipelineType(str, Enum):
    TRANSLATION = "TRANSLATION"
    BATCH = "BATCH"


@dataclass
class SubtitleCue:
    """Individual subtitle entry with millisecond timestamps and text."""
    index: int
    start_ms: int
    end_ms: int
    text: str

    @staticmethod
    def ms_to_timestamp(ms: int) -> str:
        if ms < 0:
            ms = 0
        total_seconds = ms // 1000
        milliseconds = ms % 1000
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    @staticmethod
    def timestamp_to_ms(ts: str) -> int:
        ts = ts.strip().replace('.', ',')
        parts = ts.split(':')
        if len(parts) == 3:
            h = int(parts[0])
            m = int(parts[1])
            sec_parts = parts[2].split(',')
            s = int(sec_parts[0])
            ms = int(sec_parts[1]) if len(sec_parts) > 1 else 0
            return (h * 3600 + m * 60 + s) * 1000 + ms
        elif len(parts) == 2:
            m = int(parts[0])
            sec_parts = parts[1].split(',')
            s = int(sec_parts[0])
            ms = int(sec_parts[1]) if len(sec_parts) > 1 else 0
            return (m * 60 + s) * 1000 + ms
        return 0

    @property
    def start_str(self) -> str:
        return self.ms_to_timestamp(self.start_ms)

    @property
    def end_str(self) -> str:
        return self.ms_to_timestamp(self.end_ms)

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)

    def shift(self, offset_ms: int) -> SubtitleCue:
        return SubtitleCue(
            index=self.index,
            start_ms=max(0, self.start_ms + offset_ms),
            end_ms=max(0, self.end_ms + offset_ms),
            text=self.text
        )

    def to_srt_block(self) -> str:
        return f"{self.index}\n{self.start_str} --> {self.end_str}\n{self.text.strip()}\n"


@dataclass
class SubtitleFile:
    """Collection of ordered subtitle cues representing an SRT file."""
    cues: List[SubtitleCue] = field(default_factory=list)
    language: str = "en"

    def to_srt(self) -> str:
        blocks = []
        for i, cue in enumerate(self.cues, 1):
            cue.index = i
            blocks.append(cue.to_srt_block())
        return "\n".join(blocks).strip() + "\n"

    def shift_all(self, offset_ms: int) -> SubtitleFile:
        return SubtitleFile(
            cues=[cue.shift(offset_ms) for cue in self.cues],
            language=self.language
        )

    def validate(self) -> tuple[bool, List[str]]:
        errors = []
        if not self.cues:
            return False, ["Subtitle file contains no cues."]
        prev_end = -1
        for i, cue in enumerate(self.cues, 1):
            if cue.end_ms <= cue.start_ms:
                errors.append(f"Cue #{i}: end time ({cue.end_str}) is not after start time ({cue.start_str}).")
            if not cue.text.strip():
                errors.append(f"Cue #{i} contains empty text.")
            prev_end = cue.end_ms
        return len(errors) == 0, errors


@dataclass
class ProviderInfo:
    provider_id: str
    display_name: str
    model_id: str
    model_display_name: str
    pipeline: str  # "TRANSLATION"
    is_free: bool
    pricing_desc: str
    free_tier_desc: str
    supports_timestamps: bool
    max_duration_sec: int
    requires_key: bool
    doc_url: str
    verification_date: str = "2026-10"
