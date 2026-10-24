"""
Tests for BatchService queue execution, folder scanning, and failure isolation in Online Subtitle Translator.
"""

from pathlib import Path
from unittest.mock import MagicMock
from app.core.types import JobStatus
from app.services.batch_service import BatchService, BatchTranslationItem


def test_batch_srt_folder_scan(tmp_path):
    s_dir = tmp_path / "subtitles"
    s_dir.mkdir()
    (s_dir / "movie1.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
    (s_dir / "movie2.en.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nWorld\n", encoding="utf-8")
    (s_dir / "movie1.fa.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nسلام\n", encoding="utf-8")

    service = BatchService()
    items = service.scan_srt_folder(s_dir, target_language="fa")

    # Should only find the 2 English SRTs and skip the already translated .fa.srt!
    assert len(items) == 2
    names = [it.name for it in items]
    assert "movie1.en.srt" in names
    assert "movie2.en.srt" in names
    assert "movie1.fa.srt" not in names


def test_batch_translation_failure_isolation(tmp_path):
    mock_trans = MagicMock()
    mock_trans.translate_srt.side_effect = [
        RuntimeError("Temporary parsing error"),
        tmp_path / "sub2.fa.srt"
    ]

    service = BatchService(translation_service=mock_trans)
    s1 = tmp_path / "sub1.srt"
    s2 = tmp_path / "sub2.srt"
    s1.write_text("1\n00:00:01,000 --> 00:00:02,000\nTest 1\n", encoding="utf-8")
    s2.write_text("1\n00:00:01,000 --> 00:00:02,000\nTest 2\n", encoding="utf-8")

    it1 = BatchTranslationItem(s1, target_language="fa")
    it2 = BatchTranslationItem(s2, target_language="ar")

    service.add_translation_item(it1)
    service.add_translation_item(it2)

    results = service.run_translation_batch(
        translation_provider="cloudflare",
        translation_model="@cf/meta/llama-3.1-8b-instruct",
        target_language="fa"
    )

    assert len(results) == 2
    assert results[0].status == JobStatus.FAILED
    assert "Temporary parsing error" in results[0].error_msg
    assert results[1].status == JobStatus.COMPLETED
    assert results[1].generated_srt == tmp_path / "sub2.fa.srt"
