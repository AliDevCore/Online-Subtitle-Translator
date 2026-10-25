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
