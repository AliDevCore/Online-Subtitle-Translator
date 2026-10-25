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


@patch.object(GeminiTranslationProvider, "_execute_with_pool")
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
def test_gemini_header_authentication_and_url_security(mock_post):
    """Verify Gemini API key is passed strictly in x-goog-api-key header and not in URL query string."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "candidates": [{
            "content": {"parts": [{"text": "1\n00:00:01,000 --> 00:00:02,000\nترجمه\n"}]}
        }]
    }
    mock_post.return_value = mock_resp

    provider = GeminiTranslationProvider(model_id="gemini-3-flash-preview", api_key="AIzaSySecretKey999")
    sub = SubtitleFile(cues=[SubtitleCue(1, 1000, 2000, "Text")])
    provider.translate(sub, target_language="fa")

    assert mock_post.called
    call_args, call_kwargs = mock_post.call_args
    url = call_args[0]
    headers = call_kwargs["headers"]

    # Security verification
    assert "?key=" not in url
    assert headers.get("x-goog-api-key") == "AIzaSySecretKey999"


@patch("requests.post")
def test_cloudflare_translation_chunking(mock_post):
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

    assert mock_post.call_count == 1
    assert len(sub_out.cues) == 1
    assert sub_out.cues[0].start_ms == 1000
    assert sub_out.cues[0].end_ms == 4500
    assert sub_out.cues[0].text == "سلام و خوش آمدید."
    assert sub_out.language == "fa"


@patch("requests.post")
def test_cloudflare_auth_failure_does_not_loop_infinitely(mock_post):
    """Verify that HTTP 401/403 halts immediately with authentication error rather than infinite looping."""
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized"
    mock_post.return_value = mock_resp

    provider = CloudflareTranslationProvider(
        model_id="@cf/meta/llama-3.1-8b-instruct",
        api_key="CFBadToken",
        account_id="CFBadAccount"
    )
    sub = SubtitleFile(cues=[SubtitleCue(1, 1000, 2000, "Hello")])

    with pytest.raises(RuntimeError) as exc_info:
        provider.translate(sub, target_language="fa")

    assert "failed authentication" in str(exc_info.value).lower() or "401" in str(exc_info.value)


@patch("requests.post")
def test_cue_mismatch_raises_clear_error_not_silent_copy(mock_post):
    """Verify that if the AI returns fewer cues than requested, it raises an error instead of copying English."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # Provide 1 cue when 2 cues were requested
    mock_resp.json.return_value = {
        "result": {
            "response": "1\n00:00:01,000 --> 00:00:02,000\nترجمه اول فقط\n"
        }
    }
    mock_post.return_value = mock_resp

    provider = CloudflareTranslationProvider(
        model_id="@cf/meta/llama-3.1-8b-instruct",
        api_key="CFToken12345678",
        account_id="CFAcct12345678"
    )
    sub = SubtitleFile(cues=[
        SubtitleCue(1, 1000, 2000, "First cue"),
        SubtitleCue(2, 2500, 4000, "Second cue")
    ])

    with pytest.raises(RuntimeError) as exc_info:
        provider.translate(sub, target_language="fa")

    assert "incomplete output" in str(exc_info.value).lower()


def test_provider_chunk_sizes():
    """Verify Gemini uses ~220 cues per chunk while Cloudflare uses 80 cues."""
    from app.providers.gemini_provider import CHUNK_SIZE as GEMINI_CHUNK
    from app.providers.cloudflare_provider import CHUNK_SIZE as CF_CHUNK

    assert 200 <= GEMINI_CHUNK <= 250, f"Gemini chunk size should be between 200 and 250, got {GEMINI_CHUNK}"
    assert CF_CHUNK == 80, f"Cloudflare chunk size should be 80, got {CF_CHUNK}"

