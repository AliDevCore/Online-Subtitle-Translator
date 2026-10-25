"""
Tests for TranslationService workflow, safety checks, and database persistence.
"""

from unittest.mock import MagicMock, patch
import pytest

from app.core.types import JobStatus
from app.services.translation_service import TranslationService


def test_source_file_overwrite_protection(tmp_path, temp_database):
    service = TranslationService(database=temp_database)
    source_srt = tmp_path / "movie.en.srt"
    source_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    # Attempting to translate to the exact same path must raise ValueError
    with pytest.raises(ValueError) as exc_info:
        service.translate_srt(
            english_srt_path=source_srt,
            provider_id="cloudflare",
            model_id="@cf/meta/llama-3.1-8b-instruct",
            target_lang="fa",
            output_path=source_srt
        )

    assert "identical to the source file" in str(exc_info.value).lower()


@patch("app.services.translation_service.get_translation_provider")
def test_translation_failure_records_failed_status_in_db(mock_get_prov, tmp_path, temp_database):
    mock_prov = MagicMock()
    mock_prov.translate.side_effect = RuntimeError("Quota reached on provider")
    mock_get_prov.return_value = mock_prov

    service = TranslationService(database=temp_database)
    source_srt = tmp_path / "sample.en.srt"
    source_srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")

    job_id = "test_fail_job_1"
    with pytest.raises(RuntimeError):
        service.translate_srt(
            english_srt_path=source_srt,
            provider_id="cloudflare",
            model_id="@cf/meta/llama-3.1-8b-instruct",
            target_lang="fa",
            job_id=job_id
        )

    job = temp_database.get_job(job_id)
    assert job is not None
    assert job["status"] == JobStatus.FAILED.value
    assert "Quota reached" in job["error_message"]


@patch("app.services.translation_service.get_translation_provider")
def test_translation_cleans_trailing_punctuation_on_output_only(mock_get_prov, tmp_path, temp_database):
    from app.core.types import SubtitleCue, SubtitleFile
    from app.core.srt_parser import SRTParser

    source_text = (
        "1\n00:00:01,000 --> 00:00:02,000\nListen!\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nI didn't hear you.\n\n"
        "3\n00:00:04,500 --> 00:00:06,000\nwhere's Mom?\n"
    )
    source_srt = tmp_path / "movie.en.srt"
    source_srt.write_text(source_text, encoding="utf-8")

    # Mock provider returning Persian translated cues with trailing punctuation
    mock_prov = MagicMock()
    mock_prov.get_info.return_value.display_name = "Mock Provider"
    mock_prov.translate.return_value = SubtitleFile(
        cues=[
            SubtitleCue(1, 1000, 2000, "گوش کن!"),
            SubtitleCue(2, 2500, 4000, "صداتو نشنیدم."),
            SubtitleCue(3, 4500, 6000, "مامان کجاست؟"),
        ],
        language="fa"
    )
    mock_get_prov.return_value = mock_prov

    service = TranslationService(database=temp_database)
    out_path = service.translate_srt(
        english_srt_path=source_srt,
        provider_id="cloudflare",
        model_id="@cf/meta/llama-3.1-8b-instruct",
        target_lang="fa"
    )

    # 1. Output file must exist and have trailing ! and . removed, while ؟ is kept
    assert out_path.exists()
    translated_sub = SRTParser.parse_file(out_path)
    assert translated_sub.cues[0].text == "گوش کن"
    assert translated_sub.cues[1].text == "صداتو نشنیدم"
    assert translated_sub.cues[2].text == "مامان کجاست؟"

    # 2. Source file must remain completely untouched!
    source_sub_after = SRTParser.parse_file(source_srt)
    assert source_sub_after.cues[0].text == "Listen!"
    assert source_sub_after.cues[1].text == "I didn't hear you."
    assert source_sub_after.cues[2].text == "where's Mom?"
