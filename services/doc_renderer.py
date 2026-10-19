"""Markdown -> branded PDF.

The agent writes documents as markdown with a small front-matter header:

    title: Incident Response Plan
    subtitle: Ransomware playbook
    type: Policy
    classification: CONFIDENTIAL
    version: 1.0
    ---
    # 1. Purpose
    ...

Supported markdown: # / ## / ### headings, paragraphs, **bold**, *italic*, `code`, [links](url),
- / * / 1. lists (two levels), - [ ] checklists, | tables |, > callouts (> **Warning:** ...),
~~~ / ``` code blocks, --- rules.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, KeepTogether, ListFlowable, ListItem, PageTemplate,
    Paragraph, Spacer, Table, TableStyle, XPreformatted,
)

FRONT_MATTER_KEYS = {"title", "subtitle", "type", "classification", "version", "author", "audience", "date"}
CLASSIFICATION_COLORS = {
    "PUBLIC": "#16A34A", "INTERNAL": "#2563EB", "CONFIDENTIAL": "#D97706",
    "RESTRICTED": "#DC2626", "SECRET": "#7F1D1D", "TLP:CLEAR": "#16A34A", "TLP:GREEN": "#16A34A",
    "TLP:AMBER": "#D97706", "TLP:RED": "#DC2626",
}


# --------------------------------------------------------------------------- #
# Fonts — prefer a Unicode TTF so arrows, ✓, accented names etc. render.
# --------------------------------------------------------------------------- #
_FONT_CANDIDATES = [
    ("DejaVuSans", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"),
    ("DejaVuSans", "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
     "/usr/share/fonts/dejavu/DejaVuSans-Oblique.ttf", "/usr/share/fonts/dejavu/DejaVuSansMono.ttf"),
    ("Segoe", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/segoeuii.ttf",
     "C:/Windows/Fonts/consola.ttf"),
    ("Arial", "/Library/Fonts/Arial Unicode.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
     "/System/Library/Fonts/Supplemental/Arial Italic.ttf", "/System/Library/Fonts/Supplemental/Courier New.ttf"),
]
_fonts: Optional[dict] = None


def fonts() -> dict:
    global _fonts
    if _fonts is not None:
        return _fonts
    for name, reg, bold, ital, mono in _FONT_CANDIDATES:
        if all(Path(p).exists() for p in (reg, bold, ital, mono)):
            try:
                pdfmetrics.registerFont(TTFont(name, reg))
                pdfmetrics.registerFont(TTFont(name + "-Bold", bold))
                pdfmetrics.registerFont(TTFont(name + "-Italic", ital))
                pdfmetrics.registerFont(TTFont(name + "Mono", mono))
                pdfmetrics.registerFontFamily(name, normal=name, bold=name + "-Bold",
                                              italic=name + "-Italic", boldItalic=name + "-Bold")
                _fonts = {"body": name, "bold": name + "-Bold", "italic": name + "-Italic",
                          "mono": name + "Mono", "unicode": True}
                return _fonts
            except Exception:
                continue
    _fonts = {"body": "Helvetica", "bold": "Helvetica-Bold", "italic": "Helvetica-Oblique",
              "mono": "Courier", "unicode": False}
    return _fonts


_ASCII_FALLBACK = {"→": "->", "←": "<-", "⇒": "=>", "≥": ">=", "≤": "<=", "≠": "!=", "⚠": "!", "…": "..."}


def clean_text(s: str) -> str:
    """Drop emoji (no PDF font has them) and map symbols the base fonts can't draw."""
    out = []
    for ch in s:
        cp = ord(ch)
        if cp >= 0x1F000 or 0xFE00 <= cp <= 0xFE0F or cp == 0x200D:
            continue
        if not fonts()["unicode"] and ch in _ASCII_FALLBACK:
            out.append(_ASCII_FALLBACK[ch])
        elif ch in _DINGBATS:
            out.append(ch)  # handled by dingbats()
        elif not fonts()["unicode"] and cp > 0xFF and unicodedata.category(ch).startswith("S"):
            continue
        else:
            out.append(ch)
    return "".join(out)


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
@dataclass
class DocSource:
    meta: dict = field(default_factory=dict)
    body: str = ""

    @property
    def title(self) -> str:
        return self.meta.get("title") or _first_heading(self.body) or "Untitled document"


def parse_source(text: str) -> DocSource:
    """Split optional `key: value` front matter (ended by ---) from the markdown body."""
    text = (text or "").replace("\r\n", "\n").strip("\n")
    lines = text.split("\n")
    meta: dict = {}
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
    start = i
    while i < len(lines):
        m = re.match(r"^\s*([A-Za-z_ ]{2,20})\s*:\s*(.*)$", lines[i])
        if m and m.group(1).strip().lower() in FRONT_MATTER_KEYS:
            meta[m.group(1).strip().lower()] = m.group(2).strip().strip('"')
            i += 1
            continue
        break
    if meta and i < len(lines) and lines[i].strip() == "---":
        i += 1
    elif not meta:
        i = start if start == 0 else 0
    return DocSource(meta=meta, body="\n".join(lines[i:]).strip("\n"))


def build_source(meta: dict, body: str) -> str:
    head = "\n".join(f"{k}: {v}" for k, v in meta.items() if v)
    return f"{head}\n---\n{body.strip()}\n" if head else body.strip() + "\n"


def _first_heading(body: str) -> str:
    m = re.search(r"^#{1,2}\s+(.+)$", body or "", flags=re.M)
    return m.group(1).strip() if m else ""


# --------------------------------------------------------------------------- #
# Inline markdown -> ReportLab mini-HTML
# --------------------------------------------------------------------------- #
def inline(text: str) -> str:
    f = fonts()
    text = clean_text(text)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    codes: list[str] = []

    def stash(m):
        codes.append(m.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<link href="\2"><u>\1</u></link>', text)
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: f"<b>{m.group(1) or m.group(2)}</b>", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"~~(.+?)~~", r"<strike>\1</strike>", text)
    text = re.sub(r"\x00(\d+)\x00",
                  lambda m: f'<font face="{f["mono"]}" backColor="#EEF2F7">&#160;{codes[int(m.group(1))]}&#160;</font>', text)
    return dingbats(text)


_DINGBATS = {"✓": "[x]", "✔": "[x]", "☑": "[x]", "☐": "[ ]", "✗": "[-]", "✘": "[-]"}
_SYMBOL_FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                 "C:/Windows/Fonts/seguisym.ttf", "/System/Library/Fonts/Apple Symbols.ttf"]
_symbol_font: Optional[str] = None


def _symbols() -> str:
    """Embedded TTF that has ✓ ☐ ☑ (base-14 ZapfDingbats isn't embedded and renders as boxes)."""
    global _symbol_font
    if _symbol_font is None:
        _symbol_font = ""
        for p in _SYMBOL_FONTS:
            if Path(p).exists():
                try:
                    pdfmetrics.registerFont(TTFont("AegisSymbols", p))
                    _symbol_font = "AegisSymbols"
                    break
                except Exception:
                    continue
    return _symbol_font


def dingbats(html: str) -> str:
    font = _symbols()
    for ch, ascii_ in _DINGBATS.items():
        if ch in html:
            html = html.replace(ch, f'<font name="{font}">{ch}</font>' if font else ascii_)
    return html


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
class DocumentRenderer:
    def __init__(self, branding: dict, logo_path: Optional[Path] = None):
        self.b = branding
        self.logo_path = logo_path
        f = fonts()
        self.accent = colors.HexColor(branding.get("accent_color") or "#0E9F6E")
        ink = colors.HexColor("#1B2230")
        muted = colors.HexColor("#5B6577")
        self.st = {
            "title": ParagraphStyle("title", fontName=f["bold"], fontSize=24, leading=29, textColor=ink, spaceAfter=4),
            "subtitle": ParagraphStyle("subtitle", fontName=f["body"], fontSize=12.5, leading=16, textColor=muted, spaceAfter=10),
            "h1": ParagraphStyle("h1", fontName=f["bold"], fontSize=15, leading=19, textColor=self.accent, spaceBefore=12, spaceAfter=5),
            "h2": ParagraphStyle("h2", fontName=f["bold"], fontSize=12.5, leading=16, textColor=ink, spaceBefore=9, spaceAfter=4),
            "h3": ParagraphStyle("h3", fontName=f["bold"], fontSize=10.5, leading=14, textColor=ink, spaceBefore=7, spaceAfter=3),
            "body": ParagraphStyle("body", fontName=f["body"], fontSize=10, leading=14.5, textColor=ink, spaceAfter=6, alignment=TA_LEFT),
            "cell": ParagraphStyle("cell", fontName=f["body"], fontSize=9, leading=12, textColor=ink),
            "cellh": ParagraphStyle("cellh", fontName=f["bold"], fontSize=9, leading=12, textColor=colors.white),
            "meta_k": ParagraphStyle("meta_k", fontName=f["bold"], fontSize=8.5, leading=11, textColor=muted),
            "meta_v": ParagraphStyle("meta_v", fontName=f["body"], fontSize=9.5, leading=12, textColor=ink),
            "code": ParagraphStyle("code", fontName=f["mono"], fontSize=8.3, leading=11, textColor=colors.HexColor("#0F172A")),
            "toc": ParagraphStyle("toc", fontName=f["body"], fontSize=9.5, leading=14, textColor=ink),
        }
        self.muted = muted

    # ---------------------------- public ------------------------------ #
    def render(self, source: DocSource, out_path: Path) -> Path:
        meta = dict(source.meta)
        meta.setdefault("classification", self.b.get("default_classification") or "INTERNAL")
        meta["classification"] = meta["classification"].upper()
        meta.setdefault("date", dt.date.today().strftime("%d %B %Y"))
        meta["title"] = source.title
        self._meta = meta

        doc = BaseDocTemplate(str(out_path), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                              topMargin=26 * mm, bottomMargin=20 * mm, title=clean_text(source.title),
                              author=self.b.get("organization") or "", subject=meta.get("type", ""),
                              creator="Hiderox Aegis")
        frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0)
        doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=self._decorate)])
        self.width = doc.width

        story = self._cover(source, meta)
        story += self._toc(source.body)
        story += self._blocks(source.body)
        doc.build(story)
        return out_path

    # ---------------------------- page chrome ------------------------- #
    def _decorate(self, canvas, doc):
        f = fonts()
        w, h = A4
        canvas.saveState()
        canvas.setFillColor(self.accent)
        canvas.rect(0, h - 6 * mm, w, 6 * mm, stroke=0, fill=1)
        x = 20 * mm
        if self.logo_path and self.logo_path.exists():
            try:
                canvas.drawImage(str(self.logo_path), x, h - 18.5 * mm, width=9 * mm, height=9 * mm,
                                 preserveAspectRatio=True, mask="auto")
                x += 11 * mm
            except Exception:
                pass
        canvas.setFillColor(colors.HexColor("#1B2230"))
        canvas.setFont(f["bold"], 10)
        canvas.drawString(x, h - 13.5 * mm, clean_text(self.b.get("organization") or ""))
        canvas.setFont(f["body"], 8)
        canvas.setFillColor(self.muted)
        canvas.drawString(x, h - 17.5 * mm, clean_text(" · ".join(filter(None, [self.b.get("tagline"), self.b.get("website")]))))

        cls = self._meta.get("classification", "")
        if cls:
            col = colors.HexColor(CLASSIFICATION_COLORS.get(cls, "#475569"))
            canvas.setFont(f["bold"], 7.5)
            tw = canvas.stringWidth(cls, f["bold"], 7.5) + 6 * mm
            canvas.setFillColor(col)
            canvas.roundRect(w - 20 * mm - tw, h - 17 * mm, tw, 6 * mm, 1.5 * mm, stroke=0, fill=1)
            canvas.setFillColor(colors.white)
            canvas.drawCentredString(w - 20 * mm - tw / 2, h - 15 * mm, cls)

        canvas.setStrokeColor(colors.HexColor("#E2E8F0"))
        canvas.setLineWidth(0.6)
        canvas.line(20 * mm, 14 * mm, w - 20 * mm, 14 * mm)
        canvas.setFont(f["body"], 7.5)
        canvas.setFillColor(self.muted)
        left = clean_text(self.b.get("footer_note") or f"{self._meta.get('title', '')}  ·  {cls}".strip(" ·"))
        canvas.drawString(20 * mm, 9.5 * mm, left[:120])
        canvas.drawRightString(w - 20 * mm, 9.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    # ---------------------------- cover -------------------------------- #
    def _cover(self, source: DocSource, meta: dict) -> list:
        out = [Spacer(1, 4 * mm)]
        if meta.get("type"):
            out.append(Paragraph(inline(meta["type"].upper()), ParagraphStyle(
                "kicker", parent=self.st["meta_k"], textColor=self.accent, fontSize=9, spaceAfter=4)))
        out.append(Paragraph(inline(source.title), self.st["title"]))
        if meta.get("subtitle"):
            out.append(Paragraph(inline(meta["subtitle"]), self.st["subtitle"]))
        rows = []
        for key, label in (("version", "Version"), ("date", "Date"), ("classification", "Classification"),
                           ("audience", "Audience"), ("author", "Prepared by")):
            val = meta.get(key) or (self.b.get("organization") if key == "author" else "")
            if val:
                rows.append([Paragraph(label.upper(), self.st["meta_k"]), Paragraph(inline(str(val)), self.st["meta_v"])])
        if rows:
            # Two-up meta grid
            grid = []
            for i in range(0, len(rows), 2):
                pair = rows[i] + (rows[i + 1] if i + 1 < len(rows) else ["", ""])
                grid.append(pair)
            t = Table(grid, colWidths=[33 * mm, self.width / 2 - 33 * mm] * 2)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F7FA")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ]))
            out += [Spacer(1, 2 * mm), t]
        out += [Spacer(1, 3 * mm), HRFlowable(width="100%", thickness=2, color=self.accent, spaceAfter=4 * mm)]
        return out

    def _toc(self, body: str) -> list:
        no_code = re.sub(r"^(~~~|```).*?^\1", "", body, flags=re.M | re.S)  # '# comments' in code aren't headings
        heads = re.findall(r"^#\s+(.+)$", no_code, flags=re.M)
        if len(heads) < 4:
            return []
        out = [Paragraph("Contents", self.st["h2"])]
        out += [Paragraph(inline(h), self.st["toc"]) for h in heads]
        out.append(Spacer(1, 4 * mm))
        return [KeepTogether(out)]

    # ---------------------------- body --------------------------------- #
    def _blocks(self, body: str) -> list:
        lines = body.replace("\t", "    ").split("\n")
        out: list = []
        i = 0
        para: list[str] = []

        def flush():
            if para:
                out.append(Paragraph(inline(" ".join(s.strip() for s in para)), self.st["body"]))
                para.clear()

        while i < len(lines):
            line = lines[i]
            s = line.strip()
            if not s:
                flush(); i += 1; continue
            fence = re.match(r"^(~~~|```)", s)
            if fence:
                flush()
                mark = fence.group(1)
                code = []
                i += 1
                while i < len(lines) and not lines[i].strip().startswith(mark):
                    code.append(lines[i]); i += 1
                i += 1
                out.append(self._code("\n".join(code)))
                continue
            h = re.match(r"^(#{1,4})\s+(.*)$", s)
            if h:
                flush()
                level = min(len(h.group(1)), 3)
                out.append(Paragraph(inline(h.group(2).strip("# ")), self.st[f"h{level}"]))
                i += 1; continue
            if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
                flush()
                out.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#CBD5E1"), spaceBefore=4, spaceAfter=6))
                i += 1; continue
            if s.startswith("|"):
                flush()
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    rows.append(lines[i].strip()); i += 1
                out.append(self._table(rows))
                continue
            if s.startswith(">"):
                flush()
                quote = []
                while i < len(lines) and lines[i].strip().startswith(">"):
                    quote.append(lines[i].strip()[1:].strip()); i += 1
                out.append(self._callout(quote))
                continue
            if re.match(r"^([-*+]|\d+[.)])\s+", s):
                flush()
                items = []
                while i < len(lines) and (re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]) or
                                          (lines[i].startswith("  ") and lines[i].strip() and items)):
                    items.append(lines[i]); i += 1
                out.append(self._list(items))
                continue
            if line.startswith("    ") and not para:
                code = []
                while i < len(lines) and (lines[i].startswith("    ") or not lines[i].strip()):
                    code.append(lines[i][4:]); i += 1
                out.append(self._code("\n".join(code).rstrip()))
                continue
            para.append(s)
            i += 1
        flush()
        return out

    def _code(self, code: str):
        pre = XPreformatted(clean_text(code).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"), self.st["code"])
        t = Table([[pre]], colWidths=[self.width])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        return KeepTogether([t, Spacer(1, 3 * mm)]) if code.count("\n") < 30 else t

    def _callout(self, lines: list[str]):
        text = " ".join(lines)
        kind = "note"
        m = re.match(r"^(\*\*)?\[?!?(warning|caution|danger|important|tip|note|info)\]?:?(\*\*)?:?\s*", text, flags=re.I)
        if m:
            kind = m.group(2).lower()
        palette = {"warning": ("#FFF7ED", "#F59E0B"), "caution": ("#FFF7ED", "#F59E0B"),
                   "danger": ("#FEF2F2", "#DC2626"), "important": ("#FEF2F2", "#DC2626"),
                   "tip": ("#ECFDF5", "#10B981"), "note": ("#EFF6FF", "#3B82F6"), "info": ("#EFF6FF", "#3B82F6")}
        bg, bar = palette.get(kind, palette["note"])
        p = Paragraph(inline(text), self.st["body"])
        t = Table([["", p]], colWidths=[1.6 * mm, self.width - 1.6 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, 0), colors.HexColor(bar)),
            ("BACKGROUND", (1, 0), (1, 0), colors.HexColor(bg)),
            ("LEFTPADDING", (1, 0), (1, 0), 8), ("RIGHTPADDING", (1, 0), (1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (0, 0), 0), ("RIGHTPADDING", (0, 0), (0, 0), 0),
        ]))
        return KeepTogether([t, Spacer(1, 3 * mm)])

    def _table(self, rows: list[str]):
        def cells(r):
            r = r.strip().strip("|")
            return [c.strip() for c in re.split(r"(?<!\\)\|", r)]
        parsed = [cells(r) for r in rows if not re.match(r"^\|?\s*:?-{2,}", r.strip().strip("|").strip())]
        if not parsed:
            return Spacer(1, 1)
        ncol = max(len(r) for r in parsed)
        data = []
        for ri, r in enumerate(parsed):
            r = r + [""] * (ncol - len(r))
            style = self.st["cellh"] if ri == 0 else self.st["cell"]
            data.append([Paragraph(inline(c), style) for c in r])
        # Width: proportional to content length, clamped
        lens = [max(len(parsed[ri][ci]) if ci < len(parsed[ri]) else 0 for ri in range(len(parsed))) for ci in range(ncol)]
        lens = [min(max(l, 6), 60) for l in lens]
        tot = sum(lens)
        widths = [self.width * l / tot for l in lens]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), self.accent),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DCE3EC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ]))
        return KeepTogether([t, Spacer(1, 4 * mm)]) if len(data) < 15 else t

    def _list(self, raw: list[str]):
        """Two-level bullets / numbers / checkboxes."""
        items: list[tuple[int, str, str]] = []  # (level, marker, text)
        for line in raw:
            m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", line)
            if m:
                level = 1 if len(m.group(1)) >= 2 else 0
                items.append((level, m.group(2), m.group(3)))
            elif items:
                lvl, mk, txt = items[-1]
                items[-1] = (lvl, mk, txt + " " + line.strip())
        return self._list_level(items, 0)

    def _list_level(self, items, level):
        ordered = bool(items) and items[0][1][0].isdigit()
        f = fonts()
        flow = []
        i = 0
        while i < len(items):
            lvl, mk, txt = items[i]
            if lvl > level:
                i += 1
                continue
            children = []
            j = i + 1
            while j < len(items) and items[j][0] > level:
                children.append(items[j]); j += 1
            box = re.match(r"^\[( |x|X)\]\s+(.*)$", txt)
            if box:
                mark = dingbats("☑" if box.group(1).lower() == "x" else "☐")
                txt_html = f"{mark}&#160;&#160;{inline(box.group(2))}"
            else:
                txt_html = inline(txt)
            content = [Paragraph(txt_html, ParagraphStyle("li", parent=self.st["body"], spaceAfter=2))]
            if children:
                content.append(self._list_level([(c[0] - 1, c[1], c[2]) for c in children], 0))
            flow.append(ListItem(content, value=None))
            i = j
        kw = dict(bulletFontName=f["body"], bulletFontSize=9, leftIndent=14, bulletColor=self.accent)
        if ordered:
            lf = ListFlowable(flow, bulletType="1", bulletFormat="%s.", **kw)
        elif all(re.match(r"^\[( |x|X)\]", it[2]) for it in items if it[0] == level):
            lf = ListFlowable(flow, bulletType="bullet", start="", **kw)
        else:
            lf = ListFlowable(flow, bulletType="bullet", start="•" if level == 0 else "–", **kw)
        return lf
