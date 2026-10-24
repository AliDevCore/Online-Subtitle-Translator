# Online Subtitle Translator 🌐✍️

**Online Subtitle Translator** is a high-performance Windows desktop application engineered for translating SubRip (`.srt`) subtitle files into multiple target languages (Persian, Arabic, Spanish, French, German, Turkish, Russian, and more) with strictly preserved cue timings and formatting.

Powered by modern cloud AI models (**Google Gemini** and **Cloudflare Workers AI Llama 3.1 8B Instruct**), it features an **automatic 10-account pool failover system** and **Gemini multi-model rotation**, ensuring uninterrupted translation even under strict provider rate limits and daily quotas.

---

## ✨ Key Features

- **Multi-Language Translation Engine**:
  - Direct translation from English (or any source language) into:
    - **Persian (فارسی)**
    - **Arabic (العربية)**
    - **Spanish (Español)**
    - **French (Français)**
    - **German (Deutsch)**
    - **Italian (Italiano)**
    - **Turkish (Türkçe)**
    - **Russian (Русский)**
    - **Chinese (中文)**
    - **Japanese (日本語)**
    - **Korean (한국어)**
    - **Kurdish (کوردی)**
    - **Hindi (हिन्दी)**
    - **Urdu (اردو)**
    - **Portuguese (Português)**
    - **Dutch (Nederlands)**, and more.
- **10-Account Multi-Account Rotation (Zero Downtime)**:
  - **Google Gemini Pool**: Configure up to 10 separate Google AI Studio API keys.
  - **Cloudflare Workers AI Pool**: Configure up to 10 Cloudflare Account ID + API Token pairs (10,000 free Neurons/day each = up to 100,000 free Neurons/day).
  - Automatically switches to the next account slot if rate limits (HTTP 429) or daily quotas are encountered.
- **Gemini Multi-Model Dynamic Rotation**:
  - Transparently cycles across candidate Flash models (`gemini-3-flash-preview`, `gemini-3.5-flash-lite`, `gemini-flash-lite-latest`, `gemini-3.1-flash-lite`, `gemini-3.8-flash`, etc.) before falling over to the next account.
- **Strict Timestamp & Formatting Preservation**:
  - Exact preservation of cue numbers, monotonic timestamps (`HH:MM:SS,mmm --> HH:MM:SS,mmm`), and cue counts.
  - Clean output free of extraneous markdown artifacts or AI conversational padding.
- **Batch Processing Queue**:
  - Add individual `.srt` files or scan entire directories.
  - Individual item failure isolation (one faulty file never halts the rest of the queue).
  - Real-time progress tracking and rate-limit countdown alerts.
- **Enterprise-Grade Security**:
  - API credentials are stored exclusively in the **Windows Credential Manager** (via OS keyring).
  - Zero plaintext storage in settings files, databases, or logs.
  - Automatic redaction of API keys from log outputs.
- **Lightweight & Portable**:
  - No Python runtime or external media dependencies required for the portable executable.

---

## 🚀 Installation & Quick Start

### Option 1: Portable Standalone Executable (Recommended)
1. Download the latest portable release archive (Online-Subtitle-Translator-v*.zip) from the [Releases](https://github.com/your-username/Online-Subtitle-Translator/releases) page.
2. Extract the .zip archive to any directory of your choice.
3. Run Online Subtitle Translator.exe.

### Option 2: Run from Source

```bash
# Clone the repository
git clone https://github.com/your-username/Online-Subtitle-Translator.git
cd "Online Subtitle Translator"

# Install dependencies
pip install -r requirements.txt

# Run application
python app/main.py
```

---

## 🔑 Multi-Account Setup

1. Open the application.
2. Click **API Accounts (10 Slots)** in the top toolbar.
3. Select your provider tab (**Google Gemini** or **Cloudflare Workers AI**).
4. Choose an Account Slot (Slot 1 to 10), paste your API key or token credentials, and click **Save This Account**.
5. Repeat for any backup accounts you wish to include in the auto-failover pool.

---

## 🧪 Automated Testing

Run the full pytest test suite:

```bash
python -m pytest tests -v
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) for details.
