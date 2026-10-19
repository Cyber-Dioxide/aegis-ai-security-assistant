"""Document library: each document is a markdown source (.md) + its rendered PDF, side by side."""
from __future__ import annotations

import datetime as dt
import re
import secrets
from pathlib import Path
from typing import Optional

from .doc_renderer import DocumentRenderer, parse_source

_ID = re.compile(r"^[a-z0-9-]{1,60}_[a-f0-9]{6}$")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "document").lower()).strip("-")
    return (s or "document")[:50]


class DocumentLibrary:
    def __init__(self, folder: Path, branding_provider, logo_provider):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.branding_provider = branding_provider
        self.logo_provider = logo_provider

    def _paths(self, doc_id: str) -> tuple[Path, Path]:
        if not _ID.match(doc_id or ""):
            raise ValueError("Invalid document id")
        return self.folder / f"{doc_id}.md", self.folder / f"{doc_id}.pdf"

    def save(self, source_text: str, doc_id: Optional[str] = None) -> dict:
        """Render markdown to PDF. Re-uses `doc_id` (overwrite) when given, otherwise creates a new doc."""
        source = parse_source(source_text)
        if not source.body.strip():
            raise ValueError("The document is empty.")
        if not doc_id:
            doc_id = f"{slugify(source.title)}_{secrets.token_hex(3)}"
        md_path, pdf_path = self._paths(doc_id)
        md_path.write_text(source_text.strip() + "\n", encoding="utf-8")
        DocumentRenderer(self.branding_provider(), self.logo_provider()).render(source, pdf_path)
        return self.info(doc_id)

    def info(self, doc_id: str) -> dict:
        md_path, pdf_path = self._paths(doc_id)
        if not md_path.exists():
            raise FileNotFoundError(doc_id)
        source = parse_source(md_path.read_text(encoding="utf-8"))
        words = len(re.findall(r"\w+", source.body))
        return {
            "id": doc_id,
            "title": source.title,
            "meta": source.meta,
            "words": words,
            "pages_hint": max(1, round(words / 450)),
            "pdf_url": f"/api/documents/{doc_id}.pdf",
            "md_url": f"/api/documents/{doc_id}.md",
            "updated_at": dt.datetime.fromtimestamp(md_path.stat().st_mtime).isoformat(timespec="seconds"),
            "has_pdf": pdf_path.exists(),
        }

    def source(self, doc_id: str) -> str:
        md_path, _ = self._paths(doc_id)
        return md_path.read_text(encoding="utf-8")

    def list(self) -> list[dict]:
        out = []
        for md in sorted(self.folder.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                out.append(self.info(md.stem))
            except (ValueError, FileNotFoundError, OSError):
                continue
        return out

    def delete(self, doc_id: str) -> bool:
        md_path, pdf_path = self._paths(doc_id)
        found = md_path.exists() or pdf_path.exists()
        md_path.unlink(missing_ok=True)
        pdf_path.unlink(missing_ok=True)
        return found

    def file_path(self, filename: str) -> Optional[Path]:
        stem, _, ext = filename.rpartition(".")
        if ext not in ("pdf", "md"):
            return None
        try:
            md_path, pdf_path = self._paths(stem)
        except ValueError:
            return None
        p = pdf_path if ext == "pdf" else md_path
        return p if p.exists() else None
