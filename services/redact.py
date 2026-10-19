"""Reversible PII / secret redaction.

Before a conversation is sent to a cloud LLM, sensitive values are swapped for placeholders like
[EMAIL_1]. The model works with the placeholders; the app swaps the real values back into the reply
and into generated documents, so they never leave the machine.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Order matters: secrets and specific formats first so generic patterns don't eat them.
PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("PRIVATE_KEY", "private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----")),
    ("JWT", "token", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")),
    ("API_KEY", "API key", re.compile(
        r"\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{36,}"
        r"|glpat-[A-Za-z0-9_-]{20,}|xox[abpr]-[A-Za-z0-9-]{10,}|gsk_[A-Za-z0-9]{40,}|hf_[A-Za-z0-9]{30,})\b")),
    # Only the value after "password:" is masked (group 2); the label stays readable.
    ("PASSWORD", "password", re.compile(r"(?i)(\b(?:password|passwd|pwd|pass)\s*[:=]\s*)([^\s'\"]{4,})")),
    ("EMAIL", "email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("IBAN", "IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4}\d{7}[A-Z0-9]{0,16}\b")),
    ("CARD", "card number", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("CNIC", "national ID", re.compile(r"\b\d{5}-\d{7}-\d\b")),
    ("SSN", "SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP", "IP address", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
    ("PHONE", "phone number", re.compile(r"(?<![\w.])\+?\d[\d\s().-]{8,16}\d(?![\w.])")),
]

# Private / documentation ranges are rarely sensitive and often the point of the question.
_SAFE_IPS = re.compile(r"^(?:127\.|0\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)")


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


@dataclass
class Redactor:
    mapping: dict[str, str] = field(default_factory=dict)   # placeholder -> original
    _reverse: dict[str, str] = field(default_factory=dict)  # original -> placeholder
    counts: dict[str, int] = field(default_factory=dict)    # human label -> count

    def redact(self, text: str) -> str:
        for kind, label, pattern in PATTERNS:
            if kind == "PASSWORD":
                text = pattern.sub(lambda m, k=kind, l=label: m.group(1) + self._swap(m.group(2), k, l), text)
            else:
                text = pattern.sub(lambda m, k=kind, l=label: self._swap(m.group(0), k, l), text)
        return text

    def _swap(self, value: str, kind: str, label: str) -> str:
        if value.startswith("[") and value.endswith("]") and value[1:-1].split("_")[0] in {k for k, _, _ in PATTERNS}:
            return value
        if kind == "CARD":
            digits = re.sub(r"\D", "", value)
            if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                return value
        if kind == "IP" and _SAFE_IPS.match(value):
            return value
        if kind == "PHONE" and (len(re.sub(r"\D", "", value)) < 10 or re.fullmatch(r"\d+(?:\.\d+){2,}", value)):
            return value  # too short, or an IP / version number like 192.168.100.200
        if value in self._reverse:
            return self._reverse[value]
        n = sum(1 for p in self.mapping if p.startswith(f"[{kind}_")) + 1
        placeholder = f"[{kind}_{n}]"
        self.mapping[placeholder] = value
        self._reverse[value] = placeholder
        self.counts[label] = self.counts.get(label, 0) + 1
        return placeholder

    def restore(self, text: str) -> str:
        if not self.mapping or not text:
            return text
        for placeholder, original in sorted(self.mapping.items(), key=lambda kv: -len(kv[0])):
            text = text.replace(placeholder, original)
        return text

    def summary(self) -> list[str]:
        return [f"{n} {label}{'' if n == 1 else 's'}" for label, n in self.counts.items()]
