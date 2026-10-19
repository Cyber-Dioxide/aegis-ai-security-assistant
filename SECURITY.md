# Security Policy

## Reporting a vulnerability

Please **don't open a public issue** for security problems. Report them privately to Hiderox Technologies:

- ✉️ **Email:** [info@hiderox.com](mailto:info@hiderox.com) (subject: `SECURITY: Aegis`)
- 💬 **Telegram (end-to-end encrypted):** [@hiderox](https://t.me/hiderox)
- 🔐 **GitHub:** "Report a vulnerability" (private advisory) on this repository
- Policy: [hiderox.com/legal/security](https://hiderox.com/legal/security)

Please include:

- a description and impact,
- steps to reproduce / proof of concept,
- affected version (`Settings` shows it) and deployment type.

We aim to acknowledge reports within 3 business days and to ship a fix or mitigation within 30 days for
high-severity issues. We're happy to credit you in the release notes.

## Supported versions

Only the latest release on `main` receives security fixes.

## Hardening checklist for operators

- Keep the default `AEGIS_HOST=127.0.0.1` unless you need remote access; if you expose it, set a long
  `AEGIS_ACCESS_TOKEN` (the deploy script does this) and serve it over **HTTPS** with
  `AEGIS_SECURE_COOKIES=1`.
- Prefer a local Ollama model for sensitive work. With cloud providers, keep **PII masking** on
  (Settings → Privacy) and remember the provider still sees the rest of your text.
- `data/secrets.json` holds API keys (mode 600). Back up `data/` securely and never commit it.
- Run via `deploy/deploy.sh`: it uses a dedicated user and a sandboxed systemd unit.
- Keep the OS, Python packages (`pip install -U -r requirements.txt`) and Ollama updated.

## Built-in protections

- Optional token login with brute-force lockout, signed `HttpOnly`/`SameSite=Strict` session cookies.
- Content-Security-Policy, `X-Frame-Options`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`.
- Strict id validation on document paths (no traversal); uploaded logos are checked by magic bytes.
- No telemetry; chats live only in the user's browser.
