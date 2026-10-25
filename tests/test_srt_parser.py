"""
Tests for SRT parser, validator, normalizer, and serializer.
"""

from pathlib import Path
import pytest
from app.core.srt_parser import SRTParser
from app.core.types import SubtitleCue, SubtitleFile


def test_parse_valid_srt(sample_srt_text):
    sub = SRTParser.parse_text(sample_srt_text)
    assert len(sub.cues) == 3
    assert sub.cues[0].index == 1
    assert sub.cues[0].start_str == "00:00:01,000"
    assert sub.cues[0].end_str == "00:00:04,500"
    assert sub.cues[0].text == "Hello and welcome to the tutorial."
    assert sub.cues[2].text == "Let's get started right away."


def test_srt_roundtrip_serialization(sample_srt_text, tmp_path):
    sub = SRTParser.parse_text(sample_srt_text)
    out_file = tmp_path / "output.srt"
    SRTParser.write_file(sub, out_file)

    assert out_file.exists()
    reparsed = SRTParser.parse_file(out_file)
    assert len(reparsed.cues) == len(sub.cues)
    for c1, c2 in zip(sub.cues, reparsed.cues):
        assert c1.start_ms == c2.start_ms
        assert c1.end_ms == c2.end_ms
        assert c1.text == c2.text


def test_parse_with_bom():
    text_with_bom = "\ufeff1\n00:00:00,100 --> 00:00:02,000\nBOM Test\n"
    sub = SRTParser.parse_text(text_with_bom)
    assert len(sub.cues) == 1
    assert sub.cues[0].text == "BOM Test"


def test_parse_cue_with_internal_blank_line():
    text = (
        "1\n"
        "00:00:01,000 --> 00:00:03,500\n"
        "First dialogue line\n\n"
        "- Second speaker line\n\n"
        "2\n"
        "00:00:04,000 --> 00:00:06,000\n"
        "Subsequent cue text\n"
    )
    sub = SRTParser.parse_text(text)
    assert len(sub.cues) == 2
    assert "First dialogue line\n\n- Second speaker line" == sub.cues[0].text
    assert sub.cues[1].text == "Subsequent cue text"


def test_parse_cp1256_arabic_persian_subtitles(tmp_path):
    persian_srt = (
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "\u0633\u0644\u0627\u0645 \u062e\u0648\u0628\u064a\u062f\n"
    )
    raw_cp1256 = persian_srt.encode("cp1256")
    file_path = tmp_path / "persian_cp1256.srt"
    file_path.write_bytes(raw_cp1256)

    sub = SRTParser.parse_file(file_path)
    assert len(sub.cues) == 1
    assert sub.cues[0].text == "\u0633\u0644\u0627\u0645 \u062e\u0648\u0628\u064a\u062f"


def test_atomic_write_and_overwrite_protection(tmp_path):
    sub = SubtitleFile(cues=[SubtitleCue(1, 1000, 2000, "Sample")], language="en")
    target = tmp_path / "test_write.srt"

    # Initial write
    SRTParser.write_file(sub, target, overwrite=False)
    assert target.exists()

    # Disallowed overwrite
    with pytest.raises(FileExistsError):
        SRTParser.write_file(sub, target, overwrite=False)

    # Allowed overwrite
    SRTParser.write_file(sub, target, overwrite=True)
    assert target.exists()


def test_validate_cues():
    valid_cues = [
        SubtitleCue(1, 1000, 3000, "First cue"),
        SubtitleCue(2, 3500, 5000, "Second cue")
    ]
    issues = SRTParser.validate_cues(valid_cues)
    assert len(issues) == 0

    bad_cues = [
        SubtitleCue(1, 4000, 2000, "Inverted timestamps"),
        SubtitleCue(2, 5000, 6000, "")
    ]
    issues = SRTParser.validate_cues(bad_cues)
    assert len(issues) >= 2
