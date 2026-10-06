"""Biçimlendirme ve tarih yardımcıları."""
from __future__ import annotations

from datetime import date, datetime

CURRENCY_SYMBOLS = {"TRY": "₺", "USD": "$", "EUR": "€"}
MONTHS_SHORT = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]
MONTHS_LONG = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos",
               "Eylül", "Ekim", "Kasım", "Aralık"]

_symbol = "₺"
_hidden = False
MASK = "••••"


def set_hidden(v: bool) -> None:
    """Hassas (parasal) verileri gizler: money() maskeli metin döndürür."""
    global _hidden
    _hidden = bool(v)


def is_hidden() -> bool:
    return _hidden


def set_currency(code: str) -> None:
    global _symbol
    _symbol = CURRENCY_SYMBOLS.get(code, "₺")


def num(x: float | int | None, decimals: int = 2) -> str:
    """Türkçe sayı biçimi: 1.234,5 (gereksiz ondalıklar atılır)."""
    x = float(x or 0)
    s = f"{abs(x):,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if decimals and "," in s:
        s = s.rstrip("0").rstrip(",")
    return ("-" if x < 0 else "") + s


def money(x: float | int | None, sign: bool = False) -> str:
    if _hidden:
        return f"{_symbol}{MASK}"
    x = float(x or 0)
    prefix = "-" if x < 0 else ("+" if sign and x > 0 else "")
    return f"{prefix}{_symbol}{num(abs(x))}"


def pct(x: float | None, decimals: int = 1) -> str:
    return f"%{num(x or 0, decimals)}"


def to_date(s: str | date | None) -> date | None:
    if s is None or s == "":
        return None
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def dmy(s: str | date | None) -> str:
    d = to_date(s)
    return d.strftime("%d.%m.%Y") if d else "-"


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def month_label(key: str) -> str:
    y, m = key.split("-")
    return f"{MONTHS_LONG[int(m) - 1]} {y}"


def prev_month_key(key: str) -> str:
    y, m = map(int, key.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def change_pct(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return (cur - prev) / abs(prev) * 100


_TR_LOWER = str.maketrans({"I": "ı", "İ": "i"})


def tr_lower(s) -> str:
    return str(s).translate(_TR_LOWER).lower()


def initials(name: str) -> str:
    parts = [p for p in (name or "").split() if p]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


_TR_ASCII = str.maketrans({
    "ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G", "ı": "i", "İ": "I",
    "ö": "o", "Ö": "O", "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
})


def tr_ascii(s: str) -> str:
    """Türkçe karakterleri ASCII karşılıklarına çevirir (kod üretimi için)."""
    return str(s or "").translate(_TR_ASCII)
