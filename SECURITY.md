# Security Policy

## Credential Storage

Online Subtitle Translator treats user API keys and authentication tokens with care:
- **Windows Credential Manager**: Credentials (Google Gemini and Cloudflare API keys) are stored securely in the OS credential store via Windows DPAPI.
- **Memory Caching**: Sensitive keys are cached in memory during active sessions to eliminate DPAPI latency and avoid frequent disk and OS API lookups.
- **Header-Based Authentication**: Google Gemini requests transmit the API key via the `x-goog-api-key` HTTP header rather than exposed in URL query parameters.
- **Redaction**: Key material is automatically redacted from application logs and diagnostic viewer outputs.
- **HTTPS Enforcement**: All remote API communications are encrypted via HTTPS.

## Reporting a Vulnerability

If you discover a security vulnerability or credential handling issue, please report it via [GitHub Private Vulnerability Reporting](https://github.com/) on the repository.
