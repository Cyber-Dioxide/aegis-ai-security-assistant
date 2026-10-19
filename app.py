"""Hiderox Aegis — self-hosted AI security & privacy assistant (Flask entry point)."""
from __future__ import annotations

import datetime as dt
import hmac
import json
import os
import secrets
import time
from pathlib import Path

from flask import (Flask, Response, abort, jsonify, redirect, render_template, request, send_file,
                   session, url_for)

from services.agent import AegisAgent
from services.documents import DocumentLibrary
from services.llm_service import PROVIDERS, LLMError, LLMManager
from services.redact import Redactor
from services.settings_service import SettingsService, mask_key

__version__ = "1.0.0"

# --------------------------------------------------------------------------- #
# Configuration (all paths writable data lives under AEGIS_DATA_DIR)
# --------------------------------------------------------------------------- #
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("AEGIS_DATA_DIR") or BASE_DIR / "data").resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
ACCESS_TOKEN = os.environ.get("AEGIS_ACCESS_TOKEN", "").strip()


def _secret_key() -> bytes:
    env = os.environ.get("AEGIS_SECRET_KEY")
    if env:
        return env.encode()
    path = DATA_DIR / ".secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip().encode()


app = Flask(__name__, template_folder=str(BASE_DIR / "templates"), static_folder=str(BASE_DIR / "static"))
app.config.update(
    SECRET_KEY=_secret_key(),
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SEND_FILE_MAX_AGE_DEFAULT=0,
    SESSION_COOKIE_NAME="aegis_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("AEGIS_SECURE_COOKIES") == "1",
    PERMANENT_SESSION_LIFETIME=dt.timedelta(days=7),
)

settings = SettingsService(DATA_DIR / "settings.json", DATA_DIR / "secrets.json")
llm = LLMManager(settings, env_overrides={k: v for k, v in os.environ.items() if k.startswith("OLLAMA_")})


def _logo_path() -> Path | None:
    for ext in ("png", "jpg", "jpeg"):
        p = DATA_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None


library = DocumentLibrary(DATA_DIR / "documents", lambda: settings.section("branding"), _logo_path)
agent = AegisAgent(settings, library)


# --------------------------------------------------------------------------- #
# Security: optional access token, headers
# --------------------------------------------------------------------------- #
_failed_logins: dict[str, list[float]] = {}
PUBLIC_PATHS = ("/login", "/static/", "/favicon.ico", "/api/health")


def _authed() -> bool:
    if not ACCESS_TOKEN:
        return True
    if session.get("auth") is True:
        return True
    header = request.headers.get("Authorization", "")
    return header.startswith("Bearer ") and hmac.compare_digest(header[7:].strip(), ACCESS_TOKEN)


@app.before_request
def _guard():
    if request.path.startswith(PUBLIC_PATHS) or _authed():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Authentication required"}), 401
    return redirect(url_for("login", next=request.path))


@app.after_request
def _security_headers(resp: Response):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
    resp.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    if resp.mimetype == "text/html":
        resp.headers.setdefault("Content-Security-Policy", (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; "
            "frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"))
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


@app.route("/login", methods=["GET", "POST"])
def login():
    if not ACCESS_TOKEN:
        return redirect("/")
    error = ""
    ip = request.remote_addr or "?"
    now = time.time()
    recent = [t for t in _failed_logins.get(ip, []) if now - t < 300]
    if request.method == "POST":
        if len(recent) >= 5:
            error = "Too many attempts. Try again in a few minutes."
        elif hmac.compare_digest((request.form.get("token") or "").strip(), ACCESS_TOKEN):
            session.clear()
            session["auth"] = True
            session.permanent = True
            _failed_logins.pop(ip, None)
            nxt = request.args.get("next") or "/"
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else "/")
        else:
            recent.append(now)
            _failed_logins[ip] = recent
            error = "That token didn't work."
    return render_template("login.html", error=error, brand=settings.section("branding"),
                           agent=settings.section("agent"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.context_processor
def _asset_version():
    static = BASE_DIR / "static"
    mtimes = [p.stat().st_mtime for p in static.rglob("*") if p.is_file()]
    js = sorted(p.name for p in (static / "js").glob("*.js"))
    return {"asset_v": int(max(mtimes, default=0)), "js_modules": js, "app_version": __version__}


def _sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# --------------------------------------------------------------------------- #
# Pages + health
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return render_template("index.html", auth_enabled=bool(ACCESS_TOKEN))


@app.route("/favicon.ico")
def favicon():
    return send_file(BASE_DIR / "static" / "img" / "logo.svg", mimetype="image/svg+xml")


@app.route("/api/health")
def health():
    data = {"status": "ok", "version": __version__}
    if not _authed():
        return jsonify(data)  # unauthenticated callers only learn that the service is up
    cfg = llm.config_for()
    data.update({
        "ai": {"provider": cfg.provider, "label": cfg.label, "model": cfg.model,
               "reachable": llm.client().is_reachable(), "local": cfg.kind == "ollama"},
        "agent": settings.section("agent"),
        "branding": settings.section("branding"),
        "privacy": settings.section("privacy"),
        "documents": len(library.list()),
        "auth_enabled": bool(ACCESS_TOKEN),
    })
    return jsonify(data)


# --------------------------------------------------------------------------- #
# Agent chat (SSE)
# --------------------------------------------------------------------------- #
@app.route("/api/agent/chat", methods=["POST"])
def agent_chat():
    """Body: {"messages": [...], "doc_id": "<open document id>"|null}

    Events: status · privacy · token · document · document_error · final · error · done
    """
    data = request.get_json(silent=True) or {}
    messages = data.get("messages") or []
    doc_id = data.get("doc_id") or None
    client = llm.client()

    def stream():
        try:
            for event in agent.run(client, messages, doc_id):
                yield _sse(event)
        except Exception as exc:  # never leave the UI hanging
            yield _sse({"type": "error", "error": f"{type(exc).__name__}: {exc}"})
        yield _sse({"type": "done"})

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #
@app.route("/api/documents")
def documents_list():
    return jsonify({"ok": True, "documents": library.list()})


@app.route("/api/documents", methods=["POST"])
def documents_save():
    data = request.get_json(silent=True) or {}
    try:
        info = library.save(data.get("source") or "", doc_id=data.get("id") or None)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Render failed: {exc}"}), 500
    return jsonify({"ok": True, "document": info})


@app.route("/api/documents/<doc_id>/source")
def documents_source(doc_id: str):
    try:
        return jsonify({"ok": True, "document": library.info(doc_id), "source": library.source(doc_id)})
    except (ValueError, FileNotFoundError):
        return jsonify({"ok": False, "error": "Not found"}), 404


@app.route("/api/documents/<name>", methods=["GET", "DELETE"])
def documents_file(name: str):
    if request.method == "DELETE":
        try:
            return jsonify({"ok": library.delete(name)})
        except ValueError:
            return jsonify({"ok": False, "error": "Invalid id"}), 400
    path = library.file_path(name)
    if not path:
        abort(404)
    inline = request.args.get("inline") in ("1", "true")
    mime = "application/pdf" if name.endswith(".pdf") else "text/markdown"
    return send_file(path, mimetype=mime, as_attachment=not inline, download_name=name)


# --------------------------------------------------------------------------- #
# AI providers
# --------------------------------------------------------------------------- #
@app.route("/api/ai/providers")
def ai_providers():
    ai = settings.section("ai")
    out = []
    for pid, meta in PROVIDERS.items():
        cfg = llm.config_for(pid)
        out.append({
            "id": pid, "label": meta["label"], "tagline": meta["tagline"], "kind": meta["kind"],
            "needs_key": meta["needs_key"], "key_url": meta["key_url"],
            "model": cfg.model, "base_url": cfg.base_url, "default_base_url": meta["base_url"],
            "suggested_models": meta["models"],
            "api_key_masked": mask_key(cfg.api_key),
            "api_key_source": settings.api_key_source(pid, meta.get("env_key")),
            "env_key": meta.get("env_key"),
        })
    return jsonify({"ok": True, "active": llm.config_for().provider, "providers": out,
                    "temperature": ai.get("temperature", 0.3)})


@app.route("/api/ai/settings", methods=["POST"])
def ai_settings():
    data = request.get_json(silent=True) or {}
    patch: dict = {"ai": {}}
    pid = data.get("provider")
    if pid:
        if pid not in PROVIDERS:
            return jsonify({"ok": False, "error": f"Unknown provider {pid}"}), 400
        prov = {}
        if "model" in data:
            prov["model"] = (data.get("model") or "").strip()
        if "base_url" in data:
            prov["base_url"] = (data.get("base_url") or "").strip().rstrip("/")
        if prov:
            patch["ai"]["providers"] = {pid: prov}
        if "api_key" in data:
            settings.set_api_key(pid, (data.get("api_key") or "").strip())
    if data.get("active_provider"):
        if data["active_provider"] not in PROVIDERS:
            return jsonify({"ok": False, "error": "Unknown provider"}), 400
        patch["ai"]["active_provider"] = data["active_provider"]
    if "temperature" in data:
        patch["ai"]["temperature"] = max(0.0, min(1.5, float(data["temperature"])))
    settings.update(patch)
    cfg = llm.config_for()
    return jsonify({"ok": True, "active": cfg.provider, "model": cfg.model, "label": cfg.label})


@app.route("/api/ai/models")
def ai_models():
    pid = request.args.get("provider") or None
    try:
        return jsonify({"ok": True, "models": llm.client(pid).list_models()})
    except LLMError as exc:
        return jsonify({"ok": False, "error": str(exc), "models": PROVIDERS.get(pid or "", {}).get("models", [])})


@app.route("/api/ai/test", methods=["POST"])
def ai_test():
    data = request.get_json(silent=True) or {}
    client = llm.client(data.get("provider") or None)
    result = client.ping()
    result.update({"provider": client.cfg.provider, "model": client.cfg.model})
    return jsonify(result)


# --------------------------------------------------------------------------- #
# Settings: persona, branding, privacy
# --------------------------------------------------------------------------- #
@app.route("/api/settings")
def get_settings():
    s = settings.get()
    return jsonify({"ok": True, **{k: s[k] for k in ("agent", "branding", "privacy")},
                    "has_logo": _logo_path() is not None})


@app.route("/api/settings", methods=["POST"])
def update_settings():
    data = request.get_json(silent=True) or {}
    patch = {k: v for k, v in data.items() if k in ("agent", "branding", "privacy") and isinstance(v, dict)}
    if not patch:
        return jsonify({"ok": False, "error": "Nothing to update"}), 400
    s = settings.update(patch)
    return jsonify({"ok": True, **{k: s[k] for k in ("agent", "branding", "privacy")}})


@app.route("/api/branding/logo", methods=["GET", "POST", "DELETE"])
def branding_logo():
    if request.method == "GET":
        p = _logo_path()
        return send_file(p) if p else send_file(BASE_DIR / "static" / "img" / "logo.svg", mimetype="image/svg+xml")
    for ext in ("png", "jpg", "jpeg"):
        (DATA_DIR / f"logo.{ext}").unlink(missing_ok=True)
    if request.method == "DELETE":
        return jsonify({"ok": True})
    file = request.files.get("file")
    ext = Path(file.filename).suffix.lower().lstrip(".") if file and file.filename else ""
    if ext not in ("png", "jpg", "jpeg"):
        return jsonify({"ok": False, "error": "Upload a PNG or JPG"}), 400
    head = file.stream.read(8)
    file.stream.seek(0)
    if not (head.startswith(b"\x89PNG") or head.startswith(b"\xff\xd8")):
        return jsonify({"ok": False, "error": "That file isn't a real PNG/JPG"}), 400
    file.save(str(DATA_DIR / f"logo.{ext}"))
    return jsonify({"ok": True})


@app.route("/api/privacy/preview", methods=["POST"])
def privacy_preview():
    """Show exactly what would be masked before text is sent to a cloud AI."""
    text = (request.get_json(silent=True) or {}).get("text") or ""
    r = Redactor()
    return jsonify({"ok": True, "redacted": r.redact(text[:20000]), "found": r.summary()})


if __name__ == "__main__":
    host = os.environ.get("AEGIS_HOST", "127.0.0.1")
    port = int(os.environ.get("AEGIS_PORT", "8080"))
    if host not in ("127.0.0.1", "localhost", "::1") and not ACCESS_TOKEN:
        print("⚠  Listening on a network interface without AEGIS_ACCESS_TOKEN — anyone on the network can use it.")
    app.run(host=host, port=port, debug=os.environ.get("AEGIS_DEBUG") == "1", threaded=True)
