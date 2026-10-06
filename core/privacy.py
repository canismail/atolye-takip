"""Hassas veri gizleme: durum data/hidden.txt'de saklanır, açmak için şifre gerekir.

Şifre koda base64 olarak yazılıdır. Değiştirmek için Terminal'de:  echo -n yeniSifre | base64
çıkan değeri PASSWORD_B64'e yazın. (Not: base64 şifreleme değil, yalnızca gözden saklamadır.)
"""
from __future__ import annotations

import base64
import hmac

from core.remote import BASE_DIR

PASSWORD_B64 = "MTIzNA=="  # varsayılan şifre: 1234
FILE = BASE_DIR / "data" / "hidden.txt"


def is_hidden() -> bool:
    try:
        return FILE.read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return False


def set_hidden(v: bool) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text("1" if v else "0", encoding="utf-8")


def check(password: str) -> bool:
    real = base64.b64decode(PASSWORD_B64).decode("utf-8")
    return hmac.compare_digest(real.encode(), (password or "").encode())
