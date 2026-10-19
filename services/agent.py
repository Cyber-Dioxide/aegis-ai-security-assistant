"""Aegis — the chat agent. Security & privacy expert, general helper, and PDF document writer.

Works with any LLM: instead of provider-specific tool calling, the model writes a fenced block

    ```document
    title: ...
    ---
    # markdown...
    ```

which the stream filter hides from the chat and the app renders into a branded PDF.
"""
from __future__ import annotations

import datetime as dt
import difflib
import re
from typing import Iterator, Optional

from .doc_renderer import parse_source
from .llm_service import LLMClient, LLMError
from .redact import Redactor

MAX_HISTORY_MESSAGES = 20
MAX_DOC_CONTEXT_CHARS = 14000
ACTION_TAGS = ("document", "doc", "pdf")

TONES = {
    "genz": (
        "Gen-Z energy: upbeat, witty, casual. Short sentences, light slang (\"lowkey\", \"no cap\", \"bet\"), "
        "at most one emoji per message. Never cringe or condescending. Switch to calm, precise language for "
        "incidents, legal/compliance topics and anything that will go in a document."
    ),
    "friendly": "Warm, friendly and encouraging. Clear and conversational. An occasional emoji is fine.",
    "professional": "Polished and professional, like a senior security consultant. Concise, no slang or emojis.",
}


# --------------------------------------------------------------------------- #
# Stream filter — splits model output into visible text and action blocks
# --------------------------------------------------------------------------- #
class ActionStreamFilter:
    def __init__(self, tags=ACTION_TAGS):
        self.tags = tags
        self.mode = "text"          # text | code | block
        self.pending = ""
        self.block_tag = ""
        self.block_buf = ""
        self.depth = 0
        self.blocks: list[tuple[str, str]] = []
        self.visible = ""

    def feed(self, chunk: str) -> list[tuple[str, str]]:
        self.pending += chunk
        return self._drain(final=False)

    def finish(self) -> list[tuple[str, str]]:
        events = self._drain(final=True)
        if self.mode == "block":  # model forgot the closing fence
            self.block_buf += self.pending
            self.pending = ""
            events += self._close_block()
        elif self.pending:
            events.append(self._emit(self.pending))
            self.pending = ""
        return events

    def _emit(self, s: str) -> tuple[str, str]:
        self.visible += s
        return ("text", s)

    def _close_block(self) -> list[tuple[str, str]]:
        body = self.block_buf.strip("\n")
        self.blocks.append(("document", body))
        self.mode, self.block_tag, self.block_buf, self.depth = "text", "", "", 0
        return [("block_end", "document")]

    def _drain(self, final: bool) -> list[tuple[str, str]]:
        events: list[tuple[str, str]] = []
        while self.pending:
            idx = self.pending.find("```")
            if self.mode == "block":
                # Line-based: a bare ``` line closes the document, unless it closes a nested
                # ```lang code block the model wrote inside the document.
                nl = self.pending.find("\n")
                if nl == -1 and not final:
                    break
                line = self.pending if nl == -1 else self.pending[:nl]
                self.pending = "" if nl == -1 else self.pending[nl + 1:]
                fence = line.strip()
                if fence == "```" and self.depth == 0:
                    events += self._close_block()
                    continue
                if fence.startswith("```"):
                    self.depth += -1 if fence == "```" else 1
                self.block_buf += line + "\n"
                continue
            if self.mode == "code":
                if idx == -1:
                    keep = 0 if final else 2
                    cut = len(self.pending) - keep
                    if cut > 0:
                        events.append(self._emit(self.pending[:cut]))
                    self.pending = self.pending[cut:]
                    break
                events.append(self._emit(self.pending[:idx + 3]))
                self.pending = self.pending[idx + 3:]
                self.mode = "text"
                continue
            if idx == -1:
                keep = 0 if final else 2
                cut = len(self.pending) - keep
                if cut > 0:
                    events.append(self._emit(self.pending[:cut]))
                self.pending = self.pending[cut:]
                break
            if idx > 0:
                events.append(self._emit(self.pending[:idx]))
                self.pending = self.pending[idx:]
            nl = self.pending.find("\n")
            if nl == -1:
                if final:
                    events.append(self._emit(self.pending))
                    self.pending = ""
                break
            tag = self.pending[3:nl].strip().lower()
            if tag in self.tags:
                self.mode, self.block_tag, self.block_buf = "block", tag, ""
                self.pending = self.pending[nl + 1:]
                events.append(("block_start", "document"))
            else:
                events.append(self._emit(self.pending[:nl + 1]))
                self.pending = self.pending[nl + 1:]
                self.mode = "code"
        return events


class StreamRestorer:
    """Swaps redaction placeholders back into streamed text without splitting a placeholder."""

    def __init__(self, redactor: Optional[Redactor]):
        self.r = redactor
        self.carry = ""

    def feed(self, s: str) -> str:
        if not self.r or not self.r.mapping:
            return s
        s = self.carry + s
        self.carry = ""
        i = s.rfind("[")
        if i != -1 and "]" not in s[i:] and len(s) - i < 24:
            self.carry, s = s[i:], s[:i]
        return self.r.restore(s)

    def flush(self) -> str:
        out, self.carry = self.carry, ""
        return self.r.restore(out) if self.r else out


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class AegisAgent:
    def __init__(self, settings, library):
        self.settings = settings
        self.library = library

    def system_prompt(self, current_doc: Optional[str], redacting: bool) -> str:
        agent = self.settings.section("agent")
        brand = self.settings.section("branding")
        name = agent.get("name") or "Aegis"
        org = brand.get("organization") or "Hiderox Technologies"
        site = brand.get("website") or ""
        tone = TONES.get(agent.get("tone"), TONES["genz"])
        custom = (agent.get("custom_instructions") or "").strip()
        default_cls = brand.get("default_classification") or "INTERNAL"
        doc_ctx = "none"
        if current_doc:
            doc_ctx = current_doc if len(current_doc) <= MAX_DOC_CONTEXT_CHARS else \
                current_doc[:MAX_DOC_CONTEXT_CHARS] + "\n[...truncated...]"

        return f"""You are {name}, the AI security & privacy assistant built by {org}{f' ({site})' if site else ''}.
Today is {dt.date.today():%A, %d %B %Y}. Your training data may be older than today — say so when recency matters.
PERSONALITY: {tone}

EXPERTISE (go deep here):
- Defensive cyber security: hardening (Windows, Linux, macOS, cloud, Microsoft 365, Google Workspace),
  network security, IAM/MFA/passkeys, backups, EDR/SIEM, logging, vulnerability management, patching.
- Incident response: triage, containment, evidence handling, ransomware, BEC, account takeover, comms.
- Phishing, scams & social engineering: analyse suspicious emails/SMS/links/headers and explain red flags.
- Privacy & data protection: GDPR, UK GDPR, CCPA/CPRA, HIPAA, PCI DSS, Pakistan's PECA 2016, data
  minimisation, DPIAs, retention, consent, cookie banners, privacy notices, data-subject requests.
- Frameworks & audits: ISO 27001/27701, SOC 2, NIST CSF 2.0, CIS Controls, OWASP Top 10/ASVS, MITRE ATT&CK.
- Secure development: code review, threat modelling (STRIDE), secrets management, supply chain, CI/CD.
- Personal privacy: account security, device settings, data-broker removal, safe travel, family safety.
You also help with anything else — general IT, DevOps, writing, research, maths, career advice.

RESPONSIBLE USE:
- Help defenders, learners, and authorised testers (pentests, CTFs, red teams with permission).
- Refuse to help with malware, credential theft, phishing kits, evading detection for malicious ends,
  unauthorised access, stalking/doxxing, or harming people — briefly say why and offer a defensive angle.
- Be accurate: never invent CVE IDs, CVSS scores, versions, laws or statistics. If unsure, say so and point
  to the authoritative source (NVD, vendor advisory, regulator). This is guidance, not legal advice.
{'- Text like [EMAIL_1], [IP_2], [API_KEY_1] are redacted placeholders for private values. Keep them exactly as written; never ask for the real values.' + chr(10) if redacting else ''}- If the user pastes a real password, key or token, warn them to rotate it.

DOCUMENTS — when the user asks for a document, policy, plan, playbook, checklist, report, assessment,
guide, procedure, handout or "a PDF", write it in ONE fenced block like this (the app turns it into a
branded PDF and shows a download card):
```document
title: Incident Response Plan
subtitle: For a 40-person company
type: Plan
classification: {default_cls}
version: 1.0
audience: IT team and management
---
# 1. Purpose
Markdown content...
```
DOCUMENT RULES:
- type is one of: Policy, Plan, Playbook, Procedure, Checklist, Guide, Report, Assessment, Handout, Memo, Template.
- classification: PUBLIC, INTERNAL, CONFIDENTIAL or RESTRICTED (or TLP:CLEAR/GREEN/AMBER/RED for threat intel).
- Make it complete, specific and actionable — real steps, owners, timelines, settings, commands. Number the
  top-level sections (# 1. …). Use tables, checklists (- [ ] item), and callouts (> **Warning:** …, > **Tip:** …).
- Inside the document, write code blocks with ~~~ (never ```), and don't use emoji.
- Use the user's organisation details if given; otherwise use neutral wording, not "[Company Name]".
- Write one or two sentences BEFORE the block and nothing after it. Don't repeat the document in chat.
- To change the CURRENT DOCUMENT, output the FULL updated document (same title) in a new block.

Otherwise answer in chat with clear markdown (headings, bullets, short code blocks). Be concise first, deeper on request.
{('OWNER INSTRUCTIONS:' + chr(10) + custom + chr(10)) if custom else ''}
CURRENT DOCUMENT (open in the editor):
{doc_ctx}"""

    def _should_redact(self, client: LLMClient) -> bool:
        p = self.settings.section("privacy")
        local = client.cfg.kind == "ollama" or re.match(r"https?://(localhost|127\.|\[::1\]|0\.0\.0\.0)", client.cfg.base_url)
        return bool(p.get("redact_for_local") if local else p.get("redact_for_cloud", True))

    def run(self, client: LLMClient, messages: list[dict], current_doc_id: Optional[str] = None) -> Iterator[dict]:
        history = [{"role": m["role"], "content": str(m.get("content") or "")}
                   for m in messages if m.get("role") in ("user", "assistant") and m.get("content")]
        history = history[-MAX_HISTORY_MESSAGES:]
        if not history or history[-1]["role"] != "user":
            yield {"type": "error", "error": "No user message to respond to."}
            return

        current_doc = None
        if current_doc_id:
            try:
                current_doc = self.library.source(current_doc_id)
            except (ValueError, FileNotFoundError, OSError):
                current_doc_id = None

        redactor = Redactor() if self._should_redact(client) else None
        if redactor:
            history = [{"role": m["role"], "content": redactor.redact(m["content"])} for m in history]
            if current_doc:
                current_doc = redactor.redact(current_doc)
            if redactor.counts:
                yield {"type": "privacy", "items": redactor.summary(), "provider": client.cfg.label}

        convo = [{"role": "system", "content": self.system_prompt(current_doc, bool(redactor))}] + history
        filt = ActionStreamFilter()
        restorer = StreamRestorer(redactor)
        yield {"type": "status", "content": "thinking"}
        try:
            for chunk in client.stream(convo, max_tokens=8192):
                for kind, payload in filt.feed(chunk):
                    if kind == "text":
                        out = restorer.feed(payload)
                        if out:
                            yield {"type": "token", "content": out}
                    elif kind == "block_start":
                        tail = restorer.flush()
                        if tail:
                            yield {"type": "token", "content": tail}
                        yield {"type": "status", "content": "writing your document"}
            for kind, payload in filt.finish():
                if kind == "text":
                    out = restorer.feed(payload)
                    if out:
                        yield {"type": "token", "content": out}
            tail = restorer.flush()
            if tail:
                yield {"type": "token", "content": tail}
        except LLMError as exc:
            yield {"type": "error", "error": str(exc)}
            return

        docs = [b for t, b in filt.blocks if t == "document"]
        if docs:
            yield {"type": "status", "content": "rendering the PDF"}
            source = redactor.restore(docs[-1]) if redactor else docs[-1]
            try:
                doc_id = self._same_doc(current_doc_id, source)
                info = self.library.save(source, doc_id=doc_id)
                info["updated"] = bool(doc_id)
                yield {"type": "document", **info}
            except Exception as exc:
                yield {"type": "document_error", "error": f"Couldn't render the PDF: {exc}"}

        text = redactor.restore(filt.visible) if redactor else filt.visible
        yield {"type": "final", "text": text.strip()}

    def _same_doc(self, current_doc_id: Optional[str], new_source: str) -> Optional[str]:
        """Overwrite the open document when the model is clearly revising it (same/similar title)."""
        if not current_doc_id:
            return None
        try:
            old_title = parse_source(self.library.source(current_doc_id)).title.lower()
        except (ValueError, FileNotFoundError, OSError):
            return None
        new_title = parse_source(new_source).title.lower()
        return current_doc_id if difflib.SequenceMatcher(None, old_title, new_title).ratio() >= 0.6 else None
