"""Provider-agnostic LLM client.

Three wire formats cover every major provider:
  * "ollama"    — native Ollama /api/chat (local models, no key)
  * "openai"    — OpenAI-compatible /chat/completions: OpenAI, Google Gemini, Groq, OpenRouter,
                  Mistral, DeepSeek, xAI, Together, LM Studio, vLLM, …
  * "anthropic" — native Anthropic Messages API

Every client exposes the same tiny surface: stream(), complete(), list_models(), ping().
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Iterator, Optional

import requests

# --------------------------------------------------------------------------- #
# Provider catalogue (defaults — model + URL can be changed in Settings)
# --------------------------------------------------------------------------- #
PROVIDERS: dict[str, dict] = {
    "ollama": {
        "label": "Ollama", "tagline": "Local & private, runs on your machine",
        "kind": "ollama", "base_url": "http://localhost:11434", "needs_key": False,
        "default_model": "gemma4:e4b", "env_key": None, "key_url": "https://ollama.com/download",
        "models": [],
    },
    "gemini": {
        "label": "Google Gemini", "tagline": "Fast, generous free tier",
        "kind": "openai", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "needs_key": True, "default_model": "gemini-3.5-flash", "env_key": "GEMINI_API_KEY",
        "key_url": "https://aistudio.google.com/apikey",
        "models": ["gemini-3.5-flash", "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-pro-latest"],
    },
    "groq": {
        "label": "Groq", "tagline": "Ridiculously fast open models",
        "kind": "openai", "base_url": "https://api.groq.com/openai/v1",
        "needs_key": True, "default_model": "llama-3.3-70b-versatile", "env_key": "GROQ_API_KEY",
        "key_url": "https://console.groq.com/keys",
        "models": ["llama-3.3-70b-versatile", "openai/gpt-oss-120b", "llama-3.1-8b-instant"],
    },
    "openai": {
        "label": "OpenAI", "tagline": "GPT models",
        "kind": "openai", "base_url": "https://api.openai.com/v1",
        "needs_key": True, "default_model": "gpt-4.1-mini", "env_key": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models": ["gpt-4.1-mini", "gpt-4.1", "gpt-4o-mini"],
    },
    "anthropic": {
        "label": "Anthropic Claude", "tagline": "Careful, sharp reasoning",
        "kind": "anthropic", "base_url": "https://api.anthropic.com",
        "needs_key": True, "default_model": "claude-haiku-5-5", "env_key": "ANTHROPIC_API_KEY",
        "key_url": "https://console.anthropic.com/settings/keys",
        "models": ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"],
    },
    "openrouter": {
        "label": "OpenRouter", "tagline": "One key, hundreds of models",
        "kind": "openai", "base_url": "https://openrouter.ai/api/v1",
        "needs_key": True, "default_model": "google/gemini-flash-latest", "env_key": "OPENROUTER_API_KEY",
        "key_url": "https://openrouter.ai/keys", "models": [],
    },
    "mistral": {
        "label": "Mistral", "tagline": "European open-weight models",
        "kind": "openai", "base_url": "https://api.mistral.ai/v1",
        "needs_key": True, "default_model": "mistral-small-latest", "env_key": "MISTRAL_API_KEY",
        "key_url": "https://console.mistral.ai/api-keys", "models": ["mistral-small-latest", "mistral-large-latest"],
    },
    "deepseek": {
        "label": "DeepSeek", "tagline": "Strong & cheap",
        "kind": "openai", "base_url": "https://api.deepseek.com/v1",
        "needs_key": True, "default_model": "deepseek-chat", "env_key": "DEEPSEEK_API_KEY",
        "key_url": "https://platform.deepseek.com/api_keys", "models": ["deepseek-chat"],
    },
    "xai": {
        "label": "xAI Grok", "tagline": "Grok models",
        "kind": "openai", "base_url": "https://api.x.ai/v1",
        "needs_key": True, "default_model": "grok-3-mini", "env_key": "XAI_API_KEY",
        "key_url": "https://console.x.ai", "models": [],
    },
    "custom": {
        "label": "Custom (OpenAI-compatible)", "tagline": "LM Studio, vLLM, LocalAI, any /v1 endpoint",
        "kind": "openai", "base_url": "http://localhost:1234/v1",
        "needs_key": False, "default_model": "", "env_key": None, "key_url": "", "models": [],
    },
}


class LLMError(RuntimeError):
    pass


@dataclass
class LLMConfig:
    provider: str
    kind: str
    base_url: str
    model: str
    api_key: str = ""
    temperature: float = 0.3
    timeout: int = 600
    num_ctx: int = 16384  # Ollama only — its default context is too small for our prompt

    @property
    def label(self) -> str:
        return PROVIDERS.get(self.provider, {}).get("label", self.provider)


def _friendly_http_error(provider: str, resp: requests.Response) -> LLMError:
    try:
        body = resp.json()
        if isinstance(body, list) and body:  # Gemini's OpenAI endpoint wraps errors in a list
            body = body[0]
        detail = body.get("error", body) if isinstance(body, dict) else body
        if isinstance(detail, dict):
            detail = detail.get("message") or json.dumps(detail)[:300]
        elif not isinstance(detail, str):
            detail = json.dumps(detail)[:300]
    except ValueError:
        detail = resp.text[:300]
    label = PROVIDERS.get(provider, {}).get("label", provider)
    if resp.status_code in (401, 403):
        return LLMError(f"{label} rejected the API key ({resp.status_code}). Check it in Settings → AI Brain. {detail}")
    if resp.status_code == 404:
        return LLMError(f"{label}: model or endpoint not found (404). {detail}")
    if resp.status_code == 429:
        return LLMError(f"{label} rate limit hit (429) — wait a moment or switch provider. {detail}")
    return LLMError(f"{label} error {resp.status_code}: {detail}")


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._ollama_caps: dict[str, list[str]] = {}

    # ---------------------------- public API -------------------------- #
    def stream(self, messages: list[dict], temperature: Optional[float] = None,
               max_tokens: int = 4096) -> Iterator[str]:
        temp = self.cfg.temperature if temperature is None else temperature
        if self.cfg.kind == "ollama":
            yield from self._ollama_stream(messages, temp)
        elif self.cfg.kind == "anthropic":
            yield from self._anthropic_stream(messages, temp, max_tokens)
        else:
            yield from self._openai_stream(messages, temp, max_tokens)

    def complete(self, messages: list[dict], temperature: Optional[float] = None, max_tokens: int = 4096) -> str:
        return "".join(self.stream(messages, temperature, max_tokens))

    def list_models(self) -> list[str]:
        c = self.cfg
        try:
            if c.kind == "ollama":
                r = requests.get(f"{c.base_url}/api/tags", timeout=5)
                r.raise_for_status()
                models = r.json().get("models", [])
                self._ollama_caps = {m.get("name", ""): m.get("capabilities") or [] for m in models}
                return [m.get("name", "") for m in models]
            if c.kind == "anthropic":
                r = requests.get(f"{c.base_url}/v1/models", headers=self._anthropic_headers(),
                                 params={"limit": 100}, timeout=10)
                if r.status_code >= 400:
                    raise _friendly_http_error(c.provider, r)
                return [m["id"] for m in r.json().get("data", [])]
            r = requests.get(f"{c.base_url}/models", headers=self._openai_headers(), timeout=10)
            if r.status_code >= 400:
                raise _friendly_http_error(c.provider, r)
            data = r.json()
            ids = [m.get("id", "") for m in (data.get("data") or data.get("models") or [])]
            return sorted({i.removeprefix("models/") for i in ids if i})
        except requests.RequestException as exc:
            raise LLMError(f"Couldn't reach {c.label} at {c.base_url}: {exc}") from exc

    def ping(self) -> dict:
        """Send a tiny prompt; returns {ok, elapsed_s, reply|error}."""
        start = time.time()
        try:
            reply = self.complete([{"role": "user", "content": "Reply with exactly: ready"}],
                                  temperature=0.0, max_tokens=300)
            return {"ok": True, "elapsed_s": round(time.time() - start, 1), "reply": reply.strip()[:80]}
        except Exception as exc:  # never 500 the Test button — show the reason instead
            msg = str(exc) if isinstance(exc, LLMError) else f"{type(exc).__name__}: {exc}"
            return {"ok": False, "elapsed_s": round(time.time() - start, 1), "error": msg}

    def is_reachable(self) -> bool:
        if self.cfg.kind == "ollama":
            try:
                return requests.get(f"{self.cfg.base_url}/api/tags", timeout=3).status_code == 200
            except requests.RequestException:
                return False
        return bool(self.cfg.api_key) or not PROVIDERS.get(self.cfg.provider, {}).get("needs_key", True)

    # ---------------------------- Ollama ------------------------------ #
    def _ollama_stream(self, messages: list[dict], temperature: float) -> Iterator[str]:
        c = self.cfg
        payload = {
            "model": c.model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temperature, "num_ctx": c.num_ctx},
        }
        if "thinking" in self._ollama_capabilities(c.model):
            payload["think"] = False  # reasoning tokens add latency and we don't show them
        try:
            with requests.post(f"{c.base_url}/api/chat", json=payload, stream=True, timeout=c.timeout) as r:
                if r.status_code >= 400:
                    raise _friendly_http_error(c.provider, r)
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("error"):
                        raise LLMError(f"Ollama: {chunk['error']}")
                    tok = (chunk.get("message") or {}).get("content", "")
                    if tok:
                        yield tok
                    if chunk.get("done"):
                        break
        except requests.Timeout as exc:
            raise LLMError(f"Ollama timed out after {c.timeout}s — the model may still be loading. "
                           "Try 'Test connection' in Settings to warm it up.") from exc
        except requests.ConnectionError as exc:
            raise LLMError(f"Ollama isn't reachable at {c.base_url}. Start it with `ollama serve`, "
                           "or switch to a cloud provider in Settings → AI Brain.") from exc

    def _ollama_capabilities(self, model: str) -> list[str]:
        if not self._ollama_caps:
            try:
                self.list_models()
            except LLMError:
                pass
        return self._ollama_caps.get(model, [])

    # ---------------------------- shared ------------------------------ #
    def _post_with_retry(self, url: str, headers: dict, payload: dict) -> requests.Response:
        """POST a streaming request, retrying briefly on 'busy' answers (429/500/502/503/529)."""
        delays = (2, 5)
        for attempt in range(len(delays) + 1):
            r = requests.post(url, headers=headers, json=payload, stream=True, timeout=self.cfg.timeout)
            if r.status_code not in (429, 500, 502, 503, 529) or attempt == len(delays):
                return r
            r.close()
            time.sleep(delays[attempt])
        return r

    # ---------------------------- OpenAI-compatible ------------------- #
    def _openai_headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.cfg.api_key:
            h["Authorization"] = f"Bearer {self.cfg.api_key}"
        if self.cfg.provider == "openrouter":
            h["HTTP-Referer"] = "https://hiderox.com"
            h["X-Title"] = "Hiderox Aegis"
        return h

    def _openai_stream(self, messages: list[dict], temperature: float, max_tokens: int) -> Iterator[str]:
        c = self.cfg
        if PROVIDERS.get(c.provider, {}).get("needs_key") and not c.api_key:
            raise LLMError(f"No API key set for {c.label}. Add one in Settings → AI Brain.")
        payload = {"model": c.model, "messages": messages, "stream": True,
                   "temperature": temperature, "max_tokens": max_tokens}
        if c.provider == "gemini":
            # Newer Gemini models "think" by default and can burn the whole token budget on it.
            payload["reasoning_effort"] = "low"
        try:
            with self._post_with_retry(f"{c.base_url}/chat/completions", self._openai_headers(), payload) as r:
                if r.status_code >= 400:
                    raise _friendly_http_error(c.provider, r)
                for raw in r.iter_lines(decode_unicode=False):
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace")
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(chunk, list):
                        chunk = chunk[0] if chunk and isinstance(chunk[0], dict) else {}
                    if chunk.get("error"):
                        raise LLMError(f"{c.label}: {chunk['error'].get('message', chunk['error'])}")
                    for choice in chunk.get("choices") or []:
                        tok = (choice.get("delta") or {}).get("content")
                        if tok:
                            yield tok
        except requests.Timeout as exc:
            raise LLMError(f"{c.label} timed out after {c.timeout}s.") from exc
        except requests.ConnectionError as exc:
            raise LLMError(f"Couldn't reach {c.label} at {c.base_url}. Check your internet / URL.") from exc

    # ---------------------------- Anthropic --------------------------- #
    def _anthropic_headers(self) -> dict:
        return {"x-api-key": self.cfg.api_key, "anthropic-version": "2023-06-01",
                "content-type": "application/json"}

    def _anthropic_stream(self, messages: list[dict], temperature: float, max_tokens: int) -> Iterator[str]:
        c = self.cfg
        if not c.api_key:
            raise LLMError("No API key set for Anthropic. Add one in Settings → AI Brain.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        convo: list[dict] = []
        for m in messages:
            if m["role"] == "system":
                continue
            if convo and convo[-1]["role"] == m["role"]:
                convo[-1]["content"] += "\n\n" + m["content"]
            else:
                convo.append({"role": m["role"], "content": m["content"]})
        payload = {"model": c.model, "max_tokens": max_tokens, "temperature": temperature,
                   "messages": convo, "stream": True}
        if system:
            payload["system"] = system
        try:
            with self._post_with_retry(f"{c.base_url}/v1/messages", self._anthropic_headers(), payload) as r:
                if r.status_code >= 400:
                    raise _friendly_http_error(c.provider, r)
                for raw in r.iter_lines(decode_unicode=False):
                    if not raw:
                        continue
                    line = raw.decode("utf-8", errors="replace")
                    if not line.startswith("data:"):
                        continue
                    try:
                        evt = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    if evt.get("type") == "content_block_delta":
                        delta = evt.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield delta["text"]
                    elif evt.get("type") == "error":
                        raise LLMError(f"Anthropic: {(evt.get('error') or {}).get('message', evt)}")
                    elif evt.get("type") == "message_stop":
                        break
        except requests.Timeout as exc:
            raise LLMError(f"Anthropic timed out after {c.timeout}s.") from exc
        except requests.ConnectionError as exc:
            raise LLMError("Couldn't reach Anthropic. Check your internet connection.") from exc


# --------------------------------------------------------------------------- #
# Factory — builds a client from saved settings
# --------------------------------------------------------------------------- #
class LLMManager:
    """Resolves the active provider from SettingsService and hands out clients."""

    def __init__(self, settings_service, env_overrides: Optional[dict] = None):
        self.settings = settings_service
        self.env = env_overrides or {}
        self._clients: dict[tuple, LLMClient] = {}

    def config_for(self, provider: Optional[str] = None) -> LLMConfig:
        ai = self.settings.section("ai")
        provider = provider or ai.get("active_provider") or "ollama"
        if provider not in PROVIDERS:
            provider = "ollama"
        meta = PROVIDERS[provider]
        override = (ai.get("providers") or {}).get(provider, {})
        base_url = (override.get("base_url") or "").strip().rstrip("/")
        model = (override.get("model") or "").strip()
        if provider == "ollama":
            base_url = base_url or self.env.get("OLLAMA_BASE_URL", "")
            model = model or self.env.get("OLLAMA_MODEL", "")
        return LLMConfig(
            provider=provider,
            kind=meta["kind"],
            base_url=(base_url or meta["base_url"]).rstrip("/"),
            model=model or meta["default_model"],
            api_key=self.settings.get_api_key(provider, meta.get("env_key")),
            temperature=float(ai.get("temperature", 0.3)),
            timeout=int(ai.get("timeout_s", 600)),
            num_ctx=int(ai.get("ollama_num_ctx", 16384)),
        )

    def client(self, provider: Optional[str] = None) -> LLMClient:
        cfg = self.config_for(provider)
        key = (cfg.provider, cfg.base_url, cfg.model, cfg.api_key, cfg.temperature, cfg.timeout, cfg.num_ctx)
        if key not in self._clients:
            self._clients = {key: LLMClient(cfg)}  # keep only the current one
        return self._clients[key]
