"""
Application configuration, verified provider metadata, and constants for Online Subtitle Translator.
"""

from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from app.core.types import ProviderInfo, PerformanceSettings

APP_NAME = "Online Subtitle Translator"
APP_VERSION = "1.0.0"
APP_AUTHOR = "OnlineSub"

# Determine base paths and portable mode
IS_FROZEN = getattr(sys, "frozen", False)
if IS_FROZEN:
    APP_DIR = Path(sys.executable).parent.resolve()
else:
    APP_DIR = Path(__file__).resolve().parent.parent.parent

# Check for portable mode indicator (presence of portable.txt or data directory beside exe)
PORTABLE_FLAG_FILE = APP_DIR / "portable.txt"
PORTABLE_DATA_DIR = APP_DIR / "data"

if PORTABLE_FLAG_FILE.exists() or PORTABLE_DATA_DIR.exists():
    IS_PORTABLE = True
    USER_DATA_DIR = PORTABLE_DATA_DIR
else:
    IS_PORTABLE = False
    appdata = os.environ.get("APPDATA")
    if appdata:
        USER_DATA_DIR = Path(appdata) / "OnlineSubtitleTranslator"
    else:
        USER_DATA_DIR = Path.home() / ".onlinesubtitletranslator"

USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_FILE = USER_DATA_DIR / "settings.json"
DATABASE_FILE = USER_DATA_DIR / "onlinesubtitletranslator.db"
LOGS_DIR = USER_DATA_DIR / "logs"
CACHE_DIR = USER_DATA_DIR / "temp"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PERFORMANCE_SETTINGS = PerformanceSettings(
    cpu_usage_target=100,
    process_priority="Normal",
    cpu_threads="Automatic",
    ram_limit="Automatic",
    affinity_cpus=None
)

SUPPORTED_TARGET_LANGUAGES: List[Dict[str, str]] = [
    {"code": "fa", "name": "Persian (فارسی)", "native": "فارسی"},
    {"code": "ar", "name": "Arabic (العربية)", "native": "العربية"},
    {"code": "es", "name": "Spanish (Español)", "native": "Español"},
    {"code": "fr", "name": "French (Français)", "native": "Français"},
    {"code": "de", "name": "German (Deutsch)", "native": "Deutsch"},
    {"code": "it", "name": "Italian (Italiano)", "native": "Italiano"},
    {"code": "tr", "name": "Turkish (Türkçe)", "native": "Türkçe"},
    {"code": "ru", "name": "Russian (Русский)", "native": "Русский"},
    {"code": "zh", "name": "Chinese (中文)", "native": "中文"},
    {"code": "ja", "name": "Japanese (日本語)", "native": "日本語"},
    {"code": "ko", "name": "Korean (한국어)", "native": "한국어"},
    {"code": "ku", "name": "Kurdish (کوردی)", "native": "کوردی"},
    {"code": "hi", "name": "Hindi (हिन्दी)", "native": "हिन्दी"},
    {"code": "ur", "name": "Urdu (اردو)", "native": "اردو"},
    {"code": "pt", "name": "Portuguese (Português)", "native": "Português"},
    {"code": "nl", "name": "Dutch (Nederlands)", "native": "Nederlands"},
    {"code": "el", "name": "Greek (Ελληνικά)", "native": "Ελληνικά"},
    {"code": "sv", "name": "Swedish (Svenska)", "native": "Svenska"},
    {"code": "pl", "name": "Polish (Polski)", "native": "Polski"},
]


def get_app_icon():
    """Find and return the application icon across all deployment environments."""
    from PySide6.QtGui import QIcon
    candidates = [
        APP_DIR / "assets" / "app_icon.ico",
        APP_DIR / "assets" / "app_icon.png",
        APP_DIR / "_internal" / "assets" / "app_icon.ico",
        APP_DIR / "_internal" / "assets" / "app_icon.png",
        Path(__file__).resolve().parent.parent.parent / "assets" / "app_icon.ico",
        Path(__file__).resolve().parent.parent.parent / "assets" / "app_icon.png",
    ]
    if hasattr(sys, "_MEIPASS"):
        candidates.insert(0, Path(sys._MEIPASS) / "assets" / "app_icon.ico")
        candidates.insert(1, Path(sys._MEIPASS) / "assets" / "app_icon.png")

    for p in candidates:
        if p.exists():
            icon = QIcon(str(p))
            if not icon.isNull():
                return icon
    return QIcon()


# Online Subtitle Translator is dedicated exclusively to Subtitle Translation
VERIFIED_ASR_PROVIDERS: List[ProviderInfo] = []

VERIFIED_TRANSLATION_PROVIDERS: List[ProviderInfo] = [
    ProviderInfo(
        provider_id="gemini",
        display_name="Google Gemini API",
        model_id="gemini-3-flash-preview",
        model_display_name="Gemini 3 Flash Preview (Auto-Rotating Pool & Multi-Account)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="Free tier on Google AI Studio",
        free_tier_desc="High quality translation with multi-model and 10-account failover",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://ai.google.dev/gemini-api/docs",
        verification_date="2026-10"
    ),
    ProviderInfo(
        provider_id="gemini",
        display_name="Google Gemini API",
        model_id="gemini-3.5-flash-lite",
        model_display_name="Gemini 3.5 Flash-Lite (Ultra-Fast - Auto-Rotating Pool)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="Free tier on Google AI Studio",
        free_tier_desc="Ultra-fast translation with multi-model auto rotation",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://ai.google.dev/gemini-api/docs",
        verification_date="2026-10"
    ),
    ProviderInfo(
        provider_id="gemini",
        display_name="Google Gemini API",
        model_id="gemini-flash-lite-latest",
        model_display_name="Gemini Flash-Lite Latest (Auto-Rotating Pool)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="Free tier on Google AI Studio",
        free_tier_desc="Latest lightweight Flash model with auto rotation",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://ai.google.dev/gemini-api/docs",
        verification_date="2026-10"
    ),
    ProviderInfo(
        provider_id="gemini",
        display_name="Google Gemini API",
        model_id="gemini-3.1-flash-lite",
        model_display_name="Gemini 3.1 Flash-Lite (Auto-Rotating Pool)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="Free tier on Google AI Studio",
        free_tier_desc="Reliable Flash-Lite model with auto rotation",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://ai.google.dev/gemini-api/docs",
        verification_date="2026-10"
    ),
    ProviderInfo(
        provider_id="gemini",
        display_name="Google Gemini API",
        model_id="gemini-3.8-flash",
        model_display_name="Gemini 3.8 Flash (Auto-Rotating Pool)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="Free tier on Google AI Studio",
        free_tier_desc="Advanced Flash model with auto rotation",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://ai.google.dev/gemini-api/docs",
        verification_date="2026-10"
    ),
    ProviderInfo(
        provider_id="gemini",
        display_name="Google Gemini API",
        model_id="gemini-3.5-flash",
        model_display_name="Gemini 3.5 Flash (Standard - Auto-Rotating Pool)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="Free tier on Google AI Studio; Pay-as-you-go: $0.075 / 1M input tokens",
        free_tier_desc="Standard Flash translation",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://ai.google.dev/gemini-api/docs",
        verification_date="2026-10"
    ),
    ProviderInfo(
        provider_id="cloudflare",
        display_name="Cloudflare Workers AI",
        model_id="@cf/meta/llama-3.1-8b-instruct",
        model_display_name="Llama 3.1 8B Instruct (@cf/meta/llama-3.1-8b-instruct - Multi-Account Pool)",
        pipeline="TRANSLATION",
        is_free=True,
        pricing_desc="10,000 Neurons/day free; Paid: $0.011 per 1,000 Neurons",
        free_tier_desc="10,000 free daily Neurons per account across Workers AI",
        supports_timestamps=True,
        max_duration_sec=0,
        requires_key=True,
        doc_url="https://developers.cloudflare.com/workers-ai/models/llama-3.1-8b-instruct/",
        verification_date="2026-10"
    ),
]
