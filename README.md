# Online Subtitle Translator 🌐✍️

**Online Subtitle Translator** is a high-performance Windows desktop application engineered for translating SubRip (`.srt`) subtitle files into multiple target languages (Persian, Arabic, Spanish, French, German, Turkish, Russian, and 15+ more) with strictly preserved cue timings and formatting.

Powered by modern cloud AI models (**Google Gemini** and **Cloudflare Workers AI Llama 3.1 8B Instruct**), it features an **intelligent multi-account failover system** and **Gemini multi-model rotation**, ensuring reliable, uninterrupted translation even under strict provider rate limits and daily quotas.

---

## ✨ Key Features

- **Multi-Language Translation Engine**:
  - Direct translation into 19+ languages including **Persian (فارسی)**, **Arabic (العربية)**, **Spanish**, **French**, **German**, **Italian**, **Turkish**, **Russian**, **Chinese**, **Japanese**, **Korean**, **Kurdish (کوردی)**, **Hindi**, **Urdu**, **Portuguese**, **Dutch**, **Greek**, **Swedish**, and **Polish**.
- **Multi-Account Failover Pool**:
  - **Google Gemini Pool**: Configure up to 10 separate Google AI Studio API keys.
  - **Cloudflare Workers AI Pool**: Configure up to 10 Cloudflare Account ID + API Token pairs.
  - Automatically switches to the next configured account if rate limits (HTTP 429) or quota limits are encountered.
  - Remembers the last successful account across files.
- **Gemini Multi-Model Dynamic Rotation**:
  - Transparently cycles across candidate Flash models (`gemini-3-flash-preview`, `gemini-3.5-flash-lite`, `gemini-flash-lite-latest`, `gemini-3.1-flash-lite`, `gemini-3.8-flash`, etc.) before falling over to the next account.
- **Strict Cue ID & Timing Preservation**:
  - Subtitles are translated in balanced chunks (80 cues) with exact Cue ID mapping.
  - Preserves formatting tags (`<i>`, `<b>`, `{\an8}`), line breaks within dialogue, musical notes (`♪`), and speaker dashes.
  - Automatic detection and support for **UTF-8 (with/without BOM)**, **UTF-16**, and **Windows-1256 (cp1256)** Persian/Arabic subtitles.
  - Output files are saved atomically with UTF-8 BOM (`utf-8-sig`) for maximum compatibility with video players (PotPlayer, KMPlayer, VLC).
- **Batch Processing Queue**:
  - Add individual `.srt` files or scan entire directories (automatically skips already translated output files).
  - Failure isolation: an error in one file never halts the remaining queue.
  - Real-time progress tracking with separate counts for succeeded, failed, and cancelled jobs.
- **Secure Credential Management**:
  - API credentials are stored securely in the **Windows Credential Manager** (via OS DPAPI).
  - Keys are cached in memory during runtime to eliminate OS latency.
  - Gemini API keys are sent strictly via the `x-goog-api-key` HTTP header (never exposed in URL query parameters).
  - Automatic redaction of API keys from log outputs.
- **Lightweight & Portable**:
  - Standalone executable with lazy folder initialization and fallback to `%APPDATA%` if launched from read-only directories.

---

## 🚀 Installation & Quick Start

### Option 1: Portable Standalone Executable (Recommended)
1. Download `Online-Subtitle-Translator-Portable.zip` from the [Releases](https://github.com/Ali-Parhizkar/Online-Subtitle-Translator/releases) page.
2. Extract the `.zip` archive to any directory on your computer.
3. Run `Online Subtitle Translator.exe`.

> **Note on Portable Credentials:** While the application settings and logs are saved inside the application folder in portable mode, your API keys are stored encrypted within the Windows Credential Manager of the local computer.

### Option 2: Run from Source

```bash
# Clone the repository
git clone https://github.com/Ali-Parhizkar/Online-Subtitle-Translator.git
cd Online-Subtitle-Translator

# Install dependencies
pip install -r requirements.txt

# Run application
python app/main.py
```

---

## 🔒 Privacy Notice

- **Cloud Translation**: Subtitle dialogue lines are sent over encrypted HTTPS connections to either Cloudflare Workers AI or Google AI Studio APIs, depending on the provider you select.
- **Google AI Studio Free Tier**: Under Google's standard free tier terms of service, queries submitted via free API keys may be used to improve Google products. If working with private or sensitive content, consider utilizing Cloudflare or a paid Google Cloud project tier.
- **Local Logs**: Application logs and job history remain entirely local on your machine. API keys and authentication tokens are automatically redacted from all log files.

---

## 🛡️ Windows SmartScreen & Antivirus False Positives

Executable files generated with PyInstaller that lack an expensive commercial code-signing certificate may trigger a generic warning from Windows SmartScreen or certain antivirus vendors.
- Every release includes an official `SHA256SUMS.txt` checksum file generated directly by GitHub Actions CI/CD.
- You can verify the integrity of your download in PowerShell:
  ```powershell
  Get-FileHash -Algorithm SHA256 "Online-Subtitle-Translator-Portable.zip"
  ```
- If prompted by Windows SmartScreen, click **More info** and then **Run anyway**.

---

## 🔑 Multi-Account Configuration

1. Launch the application.
2. Click **API Credentials** in the toolbar.
3. Select the desired provider tab (**Google Gemini** or **Cloudflare Workers AI**).
4. Choose an Account Slot (Slot 1 to 10), enter your API key or token, and click **Save This Account**.
5. You may configure multiple accounts to manage quota separation across teams or projects.

---

## 🧪 Automated Testing

Run the full automated test suite:

```bash
python -m pytest tests -v
```

---

## 📄 License

MIT License. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for details.
