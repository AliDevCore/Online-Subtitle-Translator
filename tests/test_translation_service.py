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


def test_english_in_supported_target_languages():
    from app.core.config import SUPPORTED_TARGET_LANGUAGES, LANG_NAME_MAP
    codes = [lang["code"] for lang in SUPPORTED_TARGET_LANGUAGES]
    assert "en" in codes
    assert "en" in LANG_NAME_MAP


def test_get_default_translated_path_for_english_target(tmp_path):
    # 1. Non-English source (.fa.srt) -> .en.srt
    fa_srt = tmp_path / "movie.fa.srt"
    fa_srt.touch()
    out = TranslationService.get_default_translated_path(fa_srt, target_lang="en")
    assert out.name == "movie.en.srt"

    # 2. Non-English source (.es.srt) -> .en.srt
    es_srt = tmp_path / "cinema.es.srt"
    es_srt.touch()
    out = TranslationService.get_default_translated_path(es_srt, target_lang="en")
    assert out.name == "cinema.en.srt"

    # 3. Plain .srt without language tag -> .en.srt
    plain_srt = tmp_path / "documentary.srt"
    plain_srt.touch()
    out = TranslationService.get_default_translated_path(plain_srt, target_lang="en")
    assert out.name == "documentary.en.srt"

    # 4. Collision safe if .en.srt already exists
    existing_en = tmp_path / "movie.en.srt"
    existing_en.touch()
    out_collision = TranslationService.get_default_translated_path(fa_srt, target_lang="en")
    assert out_collision.name == "movie_1.en.srt"


@patch("app.services.translation_service.get_translation_provider")
def test_translate_foreign_subtitle_to_english(mock_get_prov, tmp_path, temp_database):
    from app.core.types import SubtitleCue, SubtitleFile
    from app.core.srt_parser import SRTParser

    source_text = (
        "1\n00:00:01,000 --> 00:00:02,000\nسلام دنیا\n\n"
        "2\n00:00:02,500 --> 00:00:04,000\nحالت چطوره؟\n"
    )
    source_srt = tmp_path / "sample.fa.srt"
    source_srt.write_text(source_text, encoding="utf-8")

    mock_prov = MagicMock()
    mock_prov.get_info.return_value.display_name = "Mock Provider"
    mock_prov.translate.return_value = SubtitleFile(
        cues=[
            SubtitleCue(1, 1000, 2000, "Hello world."),
            SubtitleCue(2, 2500, 4000, "How are you?"),
        ],
        language="en"
    )
    mock_get_prov.return_value = mock_prov

    service = TranslationService(database=temp_database)
    out_path = service.translate_srt(
        english_srt_path=source_srt,
        provider_id="gemini",
        model_id="gemini-3-flash-preview",
        target_lang="en"
    )

    assert out_path.exists()
    assert out_path.name == "sample.en.srt"
    translated_sub = SRTParser.parse_file(out_path)
    assert translated_sub.cues[0].text == "Hello world"  # Trailing period stripped
    assert translated_sub.cues[1].text == "How are you?"
