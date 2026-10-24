"""
Tests for Translation AI provider adapters with mocked network responses in Online Subtitle Translator.
"""

from unittest.mock import patch, MagicMock
import pytest

from app.core.types import SubtitleFile, SubtitleCue
from app.providers.gemini_provider import GeminiTranslationProvider
from app.providers.cloudflare_provider import CloudflareTranslationProvider


@patch("app.core.credential_manager.CredentialManager.get_gemini_accounts", return_value=[])
def test_gemini_credential_validation(mock_accts):
    p_invalid = GeminiTranslationProvider(model_id="gemini-3-flash-preview", api_key="")
    valid, msg = p_invalid.validate_credentials()
    assert valid is False

    p_valid = GeminiTranslationProvider(model_id="gemini-3-flash-preview", api_key="AIzaSyValidKey1234567890")
    valid, msg = p_valid.validate_credentials()
    assert valid is True


@patch("app.providers.gemini_provider._request_with_gemini_pool")
def test_gemini_translation_preserves_timestamps(mock_rot):
    mock_rot.return_value = ({
        "candidates": [{
            "content": {
                "parts": [{
                    "text": (
                        "1\n"
                        "00:00:01,000 --> 00:00:04,500\n"
                        "سلام و به آموزش خوش آمدید.\n"
                    )
                }]
            }
        }]
    }, "gemini-3-flash-preview")

    sub_in = SubtitleFile(
        cues=[SubtitleCue(1, 1000, 4500, "Hello and welcome to the tutorial.")],
        language="en"
    )

    provider = GeminiTranslationProvider(model_id="gemini-3-flash-preview", api_key="AIzaSyValidKey1234567890")
    sub_out = provider.translate(sub_in, target_language="fa")

    assert len(sub_out.cues) == 1
    assert sub_out.cues[0].start_ms == 1000
    assert sub_out.cues[0].end_ms == 4500
    assert sub_out.cues[0].text == "سلام و به آموزش خوش آمدید."
    assert sub_out.language == "fa"


@patch("requests.post")
def test_cloudflare_translation_single_request(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "result": {
            "response": "1\n00:00:01,000 --> 00:00:04,500\nسلام و خوش آمدید.\n"
        }
    }
    mock_post.return_value = mock_resp

    sub_in = SubtitleFile(
        cues=[SubtitleCue(1, 1000, 4500, "Hello and welcome.")],
        language="en"
    )

    provider = CloudflareTranslationProvider(
        model_id="@cf/meta/llama-3.1-8b-instruct",
        api_key="CFDummyToken12345678",
        account_id="CFAccountId12345678"
    )
    sub_out = provider.translate(sub_in, target_language="fa")

    # Assert exactly one unified POST request was sent
    assert mock_post.call_count == 1
    assert len(sub_out.cues) == 1
    assert sub_out.cues[0].start_ms == 1000
    assert sub_out.cues[0].end_ms == 4500
    assert sub_out.cues[0].text == "سلام و خوش آمدید."
    assert sub_out.language == "fa"
