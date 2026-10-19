"""App settings: `settings.json` (safe to commit) + `secrets.json` (API keys, never commit)."""
from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {
    "ai": {
        "active_provider": "ollama",
        "temperature": 0.3,
        "timeout_s": 600,
        "ollama_num_ctx": 16384,
        "providers": {},  # per-provider overrides: {"gemini": {"model": "...", "base_url": "..."}}
    },
    "agent": {
        "name": "Aegis",
        "tone": "genz",  # genz | friendly | professional
        "custom_instructions": "",
    },
    "branding": {
        "organization": "Hiderox Technologies",
        "website": "hiderox.com",
        "email": "info@hiderox.com",
        "tagline": "Cyber Security & Privacy",
        "accent_color": "#0E9F6E",
        "default_classification": "INTERNAL",
        "footer_note": "",
    },
    "privacy": {
        # Mask emails, phone numbers, IPs, card numbers, IDs and secrets before text leaves the machine.
        "redact_for_cloud": True,
        "redact_for_local": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class SettingsService:
    def __init__(self, settings_path: Path, secrets_path: Path):
        self.settings_path = Path(settings_path)
        self.secrets_path = Path(secrets_path)
        self._lock = threading.RLock()
        self._settings = self._read(self.settings_path)
        self._secrets = self._read(self.secrets_path)

    @staticmethod
    def _read(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def get(self) -> dict:
        with self._lock:
            return _deep_merge(DEFAULT_SETTINGS, self._settings)

    def section(self, name: str) -> dict:
        return self.get().get(name, {})

    def update(self, patch: dict) -> dict:
        with self._lock:
            self._settings = _deep_merge(self._settings, patch)
            self.settings_path.write_text(json.dumps(self._settings, indent=2, ensure_ascii=False), encoding="utf-8")
            return self.get()

    # ------------------------------------------------------------------ #
    # Secrets (API keys). Env vars are used when nothing is saved.
    # ------------------------------------------------------------------ #
    def get_api_key(self, provider: str, env_var: str | None = None) -> str:
        with self._lock:
            key = (self._secrets.get("api_keys") or {}).get(provider, "")
        if not key and env_var:
            key = os.environ.get(env_var, "")
        return key or ""

    def api_key_source(self, provider: str, env_var: str | None = None) -> str:
        with self._lock:
            if (self._secrets.get("api_keys") or {}).get(provider):
                return "saved"
        if env_var and os.environ.get(env_var):
            return "env"
        return ""

    def set_api_key(self, provider: str, key: str) -> None:
        with self._lock:
            keys = dict(self._secrets.get("api_keys") or {})
            if key:
                keys[provider] = key
            else:
                keys.pop(provider, None)
            self._secrets["api_keys"] = keys
            self.secrets_path.write_text(json.dumps(self._secrets, indent=2), encoding="utf-8")
            try:
                os.chmod(self.secrets_path, 0o600)  # owner-only on POSIX; no-op on Windows
            except OSError:
                pass


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:4]}…{key[-4:]}"
