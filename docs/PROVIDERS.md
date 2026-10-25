# Supported AI Translation Providers

Online Subtitle Translator features verified adapters for cloud-based LLM translation providers with multi-account pools.

---

## 1. Google Gemini API

- **Service**: Google AI Studio (Free & Paid Tiers)
- **Primary Models**:
  - `gemini-3-flash-preview`
  - `gemini-3.5-flash-lite`
  - `gemini-flash-lite-latest`
  - `gemini-3.1-flash-lite`
  - `gemini-3.8-flash`
  - `gemini-3.5-flash`
- **Features**:
  - 2-Layer Auto-Rotation: Model pool rotation combined with up to 10 Gemini API keys.
  - Header Authentication: Uses the secure `x-goog-api-key` HTTP header.
  - Formatting Preservation: Preserves subtitle styling tags (`<i>`, `<b>`, `{\an8}`), line breaks, and musical notes.
- **Recommended For**: Persian, Arabic, Turkish, and complex cinematic dialogues.

---

## 2. Cloudflare Workers AI

- **Service**: Cloudflare Workers AI
- **Primary Model**: `@cf/meta/llama-3.1-8b-instruct`
- **Pricing & Quota**:
  - Free tier: 10,000 Neurons/day per account.
  - Supports pooling across up to 10 accounts with automatic failover upon reaching 429 quota exhaustion.
- **Features**:
  - Exact Cue Index Mapping: Subtitles are chunked in batches of 80 cues with index matching.
  - Active Account Memory: Automatically starts subsequent files from the last known active account.
- **Recommended For**: European languages (Spanish, French, German, Italian, etc.) and fast bulk translations.
