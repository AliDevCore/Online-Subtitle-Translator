"""
SRT parser, validator, normalizer, and serializer.
Adheres strictly to the SRT standard (HH:MM:SS,mmm --> HH:MM:SS,mmm) and multi-encoding resilience.
"""

from __future__ import annotations
import os
import re
import uuid
from pathlib import Path
from typing import List, Tuple, Optional
from app.core.types import SubtitleCue, SubtitleFile


# Regex pattern to match timestamp lines: 00:00:00,000 --> 00:00:00,000
TIMESTAMP_PATTERN = re.compile(
    r"^(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})(.*)$"
)


class SRTParser:
    """Parser and validator for SubRip (.srt) subtitle files."""

    @staticmethod
    def parse_text(text: str, default_language: str = "en") -> SubtitleFile:
        """
        Parse raw SRT text into a SubtitleFile object.
        Accurately parses cues even when dialogue lines contain internal blank lines.
        """
        if not text:
            return SubtitleFile(cues=[], language=default_language)

        # Strip Byte Order Mark (BOM) if present
        if text.startswith("\ufeff"):
            text = text[1:]

        # Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")

        # Identify all timestamp lines and their indices
        ts_matches = []
        for idx, line in enumerate(lines):
            stripped = line.strip()
            match = TIMESTAMP_PATTERN.match(stripped)
            if match:
                ts_matches.append((idx, match))

        if not ts_matches:
            return SubtitleFile(cues=[], language=default_language)

        cues: List[SubtitleCue] = []

        for i, (ts_idx, match) in enumerate(ts_matches):
            start_str = match.group(1)
            end_str = match.group(2)
            start_ms = SubtitleCue.timestamp_to_ms(start_str)
            end_ms = SubtitleCue.timestamp_to_ms(end_str)

            # Determine cue index number if present on previous line
            cue_num = i + 1
            if ts_idx > 0:
                prev_line = lines[ts_idx - 1].strip()
                if prev_line.isdigit():
                    try:
                        cue_num = int(prev_line)
                    except ValueError:
                        pass

            # Dialogue lines are between this timestamp line and the next cue's start
            next_ts_idx = ts_matches[i + 1][0] if i + 1 < len(ts_matches) else len(lines)

            # If the next cue has a digit index line preceding its timestamp, don't include that digit in our text
            content_end = next_ts_idx
            if i + 1 < len(ts_matches) and next_ts_idx > ts_idx + 1:
                candidate_idx_line = lines[next_ts_idx - 1].strip()
                if candidate_idx_line.isdigit():
                    content_end = next_ts_idx - 1

            text_lines = lines[ts_idx + 1:content_end]
            # Strip outer blank lines but preserve internal line breaks within dialogue
            cue_text = "\n".join(text_lines).strip()

            cues.append(SubtitleCue(
                index=cue_num,
                start_ms=start_ms,
                end_ms=end_ms,
                text=cue_text
            ))

        return SubtitleFile(cues=cues, language=default_language)

    @classmethod
    def _detect_and_decode(cls, raw_bytes: bytes, explicit_encoding: Optional[str] = None) -> str:
        """Intelligently detect and decode raw subtitle bytes."""
        if explicit_encoding:
            try:
                return raw_bytes.decode(explicit_encoding)
            except UnicodeDecodeError:
                pass

        # 1. BOM detection
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            return raw_bytes.decode("utf-8-sig")
        if raw_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
            return raw_bytes.decode("utf-16")

        # 2. Strict UTF-8
        try:
            return raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            pass

        # 3. Check for cp1256 (Windows Arabic / Persian):
        try:
            candidate_cp1256 = raw_bytes.decode("cp1256")
            arabic_count = sum(1 for c in candidate_cp1256 if '\u0600' <= c <= '\u06FF')
            if arabic_count >= 1:
                return candidate_cp1256
        except Exception:
            pass

        # 4. charset_normalizer
        try:
            import charset_normalizer
            matches = charset_normalizer.from_bytes(raw_bytes)
            best = matches.best()
            if best and best.encoding:
                return str(best)
        except Exception:
            pass

        # 5. Fallback sequence
        for enc in ("cp1256", "cp1252", "iso-8859-1"):
            try:
                return raw_bytes.decode(enc)
            except UnicodeDecodeError:
                continue

        return raw_bytes.decode("utf-8", errors="replace")

    @classmethod
    def parse_file(cls, file_path: Path | str, encoding: Optional[str] = None) -> SubtitleFile:
        """
        Read and parse an SRT file from disk with intelligent encoding detection.
        Properly handles UTF-8 (with/without BOM), UTF-16, cp1256 (Persian/Arabic), and cp1252.
        """
        path = Path(file_path)
        raw_bytes = path.read_bytes()

        if not raw_bytes:
            return SubtitleFile(cues=[])

        text = cls._detect_and_decode(raw_bytes, explicit_encoding=encoding)
        return cls.parse_text(text)

    @staticmethod
    def write_file(
        subtitle_file: SubtitleFile,
        output_path: Path | str,
        overwrite: bool = False,
        bom: bool = True
    ) -> Path:
        """
        Write SubtitleFile to disk using atomic temporary-file replacement.
        Defaults to UTF-8 with BOM (utf-8-sig) to ensure maximum compatibility with media players.
        """
        path = Path(output_path).resolve()
        if path.exists() and not overwrite:
            raise FileExistsError(f"Target file already exists: {path}")

        path.parent.mkdir(parents=True, exist_ok=True)
        content = subtitle_file.to_srt()
        encoding = "utf-8-sig" if bom else "utf-8"

        # Atomic write via temporary file
        temp_path = path.with_name(f"{path.stem}.tmp_{uuid.uuid4().hex[:8]}{path.suffix}")
        try:
            temp_path.write_text(content, encoding=encoding)
            os.replace(temp_path, path)
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

        return path

    TRAILING_PUNCTUATION_TO_STRIP = {".", "!", ",", "،"}

    @classmethod
    def clean_trailing_punctuation_line(cls, line: str) -> str:
        """
        Strip trailing exclamation marks (!), commas (,, ،), or periods (.) from the end of a line.
        Strictly preserves question marks (? and ؟) and internal punctuation.
        Also handles closing HTML/formatting tags like </i> or </font>.
        """
        stripped = line.rstrip()
        if not stripped:
            return line

        tag_match = re.search(r"(</[a-zA-Z0-9]+>)+$", stripped)
        closing_tags = ""
        if tag_match:
            closing_tags = tag_match.group(0)
            stripped = stripped[:tag_match.start()].rstrip()

        while stripped and stripped[-1] in cls.TRAILING_PUNCTUATION_TO_STRIP:
            stripped = stripped[:-1].rstrip()

        return stripped + closing_tags

    @classmethod
    def clean_trailing_punctuation(cls, text: str) -> str:
        """
        Remove trailing exclamation marks (!), commas (,, ،), or periods (.) from the end of sentences/lines.
        Strictly preserves question marks (? and ؟) and preserves all punctuation in the middle of sentences.
        """
        if not text:
            return text
        lines = text.split("\n")
        return "\n".join(cls.clean_trailing_punctuation_line(l) for l in lines)

    @staticmethod
    def validate_cues(cues: List[SubtitleCue], time_range: Optional[Tuple[float, float]] = None) -> List[str]:
        """
        Validate subtitle cues for compliance:
        - Non-empty text
        - Positive duration (end_ms > start_ms)
        - Monotonic chronological start times
        - Check within time bounds if specified
        """
        issues = []
        if not cues:
            return ["No subtitle cues found."]

        prev_end = -1
        for i, cue in enumerate(cues, 1):
            if cue.end_ms <= cue.start_ms:
                issues.append(f"Cue #{i}: Duration non-positive ({cue.start_str} to {cue.end_str})")
            if not cue.text.strip():
                issues.append(f"Cue #{i}: Empty text")
            if cue.start_ms < prev_end:
                issues.append(f"Cue #{i}: Overlaps previous cue ({cue.start_str} < {SubtitleCue.ms_to_timestamp(prev_end)})")
            prev_end = cue.end_ms

            if time_range:
                start_s, end_s = time_range
                start_ms_bound = int(start_s * 1000)
                end_ms_bound = int(end_s * 1000)
                if cue.start_ms < start_ms_bound - 1000:
                    issues.append(f"Cue #{i}: Start time {cue.start_str} precedes requested segment start")
                if cue.end_ms > end_ms_bound + 2000:
                    issues.append(f"Cue #{i}: End time {cue.end_str} exceeds requested segment end")

        return issues
