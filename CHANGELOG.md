# Changelog

## [1.0.11] - 2026-11-19

### Fixed
- Fixed Cloudflare Workers AI `Read timed out` on long subtitles by reducing cue chunk sizes to optimal fast response ranges:
  - Gemma 4 26B: 35 cues/chunk (~32s per chunk)
  - Llama 3.3 70B Fast: 35 cues/chunk (~25s per chunk)
  - Qwen 3.8 27B: 30 cues/chunk (~35s per chunk)
  - GPT-OSS 120B: 30 cues/chunk (~38s per chunk)
- Fixed multi-account pool rotation in `CloudflareTranslationProvider` so all configured accounts (Accounts #1 through #10) are utilized automatically instead of pinning strictly to Account #1.
- Increased Cloudflare Workers AI network request timeout to 120 seconds to prevent premature disconnection during network latency fluctuations.

## [1.0.10] - 2026-11-19

### Added
- Configured 4 verified high-performance Cloudflare Workers AI models with model-tailored chunk sizing:
  1. Google Gemma 4 26B A4B IT (Default • ⚡ Ultra-Fast ~30s • 70 cues/chunk • Top quality cinematic translation)
  2. Alibaba Qwen 3.8 27B (⚡ Standard ~56s • 60 cues/chunk • High Persian accuracy & idiom understanding)
  3. OpenAI GPT-OSS 120B (⚡ Moderate ~42s • 50 cues/chunk • Low reasoning mode • 117B MoE)
  4. Meta Llama 3.3 70B Fast (⚡ High Speed ~24s • 60 cues/chunk • FP8 edge accelerated)
- Dynamic speed indicators in model dropdown menu for user transparency.
- Strict reasoning/thinking deactivation payload logic to prevent token bloat and gateway timeouts.
- Decoupled subtitle reconstruction guaranteeing 100% preservation of original indices and millisecond timestamps.
- Trailing punctuation cleanup and thinking/markdown tag removal on generated subtitle cues.

## [1.0.0] - 2026-10-23

### Added
- Complete Windows desktop application built with PySide6.
- Independent Speech-to-Text (ASR) and Machine Translation pipelines.
- Multi-provider support: Google Gemini, Cloudflare Workers AI, Hugging Face Inference, Local Faster-Whisper.
- Subtitle generation in valid SubRip (.srt) format with HH:MM:SS,mmm timestamps.
- Decimal minute time range entry with millisecond precision and timeline offset preservation.
- Local performance controller (CPU Usage Target 100%, Process Priority, CPU Threads, RAM Limit).
- Strict separation between local resource controls and remote cloud API processing.
- Windows Credential Manager integration for secure API key storage.
- Audio chunking with overlap and chronological merge reconciliation.
- Resumable SQLite job engine and batch processing dialog.
- Standalone portable Windows packaging script and GitHub release workflow.
