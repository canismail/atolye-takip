"""Tabloları PDF olarak dışa aktarma (Streamlit dataframe'in yerleşik "CSV olarak indir"
düğmesinin yanına eklenen "PDF olarak indir" düğmesi için)."""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
_registered = False


def _register_fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("DejaVu", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    _registered = True


def _clean(v) -> str:
    if v is None:
        return "-"
    s = str(v)
    return "-" if s in ("None", "nan", "NaT", "") else s


def table_pdf_bytes(title: str, columns: list[str], rows: list[list], company: str = "") -> bytes:
    """columns: sütun başlıkları. rows: her biri columns ile aynı sırada değer listesi."""
    _register_fonts()
    buf = io.BytesIO()
    landscape_mode = len(columns) > 5
    pagesize = landscape(A4) if landscape_mode else A4
    doc = SimpleDocTemplate(buf, pagesize=pagesize, title=title,
                            topMargin=16 * mm, bottomMargin=14 * mm, leftMargin=12 * mm, rightMargin=12 * mm)

    st_title = ParagraphStyle("t", fontName="DejaVu-Bold", fontSize=16, textColor=colors.HexColor("#172033"))
    st_sub = ParagraphStyle("s", fontName="DejaVu", fontSize=9, textColor=colors.HexColor("#68768a"), spaceAfter=10)
    st_head = ParagraphStyle("h", fontName="DejaVu-Bold", fontSize=8.5, leading=10, textColor=colors.white)
    st_cell = ParagraphStyle("c", fontName="DejaVu", fontSize=8, leading=10, textColor=colors.HexColor("#172033"))

    sub = datetime.now().strftime("%d.%m.%Y %H:%M")
    if company:
        sub = f"{company} · {sub}"
    elems = [Paragraph(title, st_title), Paragraph(sub, st_sub)]

    if rows:
        header = [Paragraph(str(c), st_head) for c in columns]
        body = [[Paragraph(_clean(v), st_cell) for v in row] for row in rows]
        data = [header] + body
        col_width = doc.width / max(len(columns), 1)
        table = Table(data, colWidths=[col_width] * len(columns), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1673d1")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fc")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e2e8f0")),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        elems.append(table)
    else:
        elems.append(Spacer(1, 6))
        elems.append(Paragraph("Kayıt yok.", st_cell))

    def _decorate(canvas, doc_):
        canvas.saveState()
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(colors.HexColor("#68768a"))
        w, _h = doc_.pagesize
        canvas.drawRightString(w - 12 * mm, 8 * mm, f"Sayfa {doc_.page}")
        canvas.restoreState()

    doc.build(elems, onFirstPage=_decorate, onLaterPages=_decorate)
    return buf.getvalue()


def slug(text: str) -> str:
    keep = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- "
    tr = str.maketrans("çğıİöşüÇĞÖŞÜ", "cgiIosuCGOSU")
    s = text.translate(tr)
    s = "".join(c if c in keep else "_" for c in s).strip().replace(" ", "_")
    while "__" in s:
        s = s.replace("__", "_")
    return s or "veri"
