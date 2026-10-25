# Online Subtitle Translator User Guide

Welcome to **Online Subtitle Translator**! This application allows you to translate `.srt` subtitle files into natural Persian, Arabic, Spanish, French, and 15+ other languages using high-performance AI models with automatic multi-account rotation.

---

## 1. Quick Walkthrough

### Step 1: Select Subtitle File
1. Click **Browse SRT File...** and select any `.srt` file.
2. The number of cues and estimated duration will appear automatically.

### Step 2: Choose Target Language and Provider
- **Target Language**: Select your desired target language (e.g., Persian, Arabic, German, Spanish).
- **AI Provider**:
  - **Google Gemini API**: Highest quality cinematic translation across candidate Flash models with 10-account failover.
  - **Cloudflare Workers AI**: Fast, free translation via Llama 3.1 8B Instruct with 10-account pool failover.
- If you haven't entered your API key yet, click **API Credentials** in the top toolbar to configure it.

### Step 3: Translate
- Click **Translate Subtitle**.
- The progress bar shows real-time chunk progress.
- When finished, the translated subtitle is saved beside the source file (e.g., `movie.fa.srt`).
- Click **Open Output Folder** to immediately access the file.

---

## 2. Batch Processing

To translate multiple subtitles or entire folders:
1. Click **Batch Subtitle Queue...** in the toolbar.
2. Click **Add SRT Files...** to select multiple files, or **Add Folder...** to automatically scan a directory for untranslated subtitles.
3. Select your desired AI provider and target language.
4. Click **Start Batch**. All files execute sequentially with automatic rate-limit failover across your configured accounts.

---

## 3. Configuring API Credentials

Click **API Credentials** in the top toolbar:
- **Google Gemini API**: Enter your Gemini API key from [Google AI Studio](https://aistudio.google.com/). You can add up to 10 keys for seamless automatic rotation.
- **Cloudflare Workers AI**: Enter your Account ID and API Token from the [Cloudflare Dashboard](https://dash.cloudflare.com/). You can add up to 10 accounts for failover across daily free limits.
- Keys are encrypted with Windows Credential Manager and cached securely in memory.
