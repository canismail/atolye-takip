"""Ürün ve malzeme fotoğrafları: yükleneni küçültüp data/images klasörüne kaydeder
(tam boy + tablo için küçük önizleme)."""
from __future__ import annotations

import base64
import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from core import db, remote

MAX_SIDE = 1200
THUMB_SIDE = 120
ALLOWED = ["png", "jpg", "jpeg", "webp"]


def _dir() -> Path:
    # Sunucu modunda fotoğraflar sunucudadır; bu klasör yalnızca indirilenlerin yerel önbelleğidir.
    d = db.DATA_DIR / ("image_cache" if remote.enabled() else "images")
    d.mkdir(parents=True, exist_ok=True)
    return d


_missing: set[str] = set()  # sunucuda bulunamayan dosyalar (tekrar tekrar sorulmasın)


def clear_cache() -> None:
    _missing.clear()
    for f in _dir().iterdir():
        try:
            f.unlink()
        except OSError:
            pass


def _thumb_name(name: str) -> str:
    return name.rsplit(".", 1)[0] + "_t.jpg"


def save_image(data: bytes, prefix: str) -> str:
    """Görseli okur (telefon yönünü düzeltir), küçültüp JPEG olarak kaydeder; dosya adını döner."""
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        img.load()
    except Exception as exc:  # bozuk / desteklenmeyen dosya
        raise ValueError("Fotoğraf okunamadı. PNG, JPG veya WEBP yükleyin.") from exc
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, "white")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    img = img.convert("RGB")
    name = f"{prefix}_{uuid.uuid4().hex[:10]}.jpg"
    full = img.copy()
    full.thumbnail((MAX_SIDE, MAX_SIDE))
    full.save(_dir() / name, "JPEG", quality=85, optimize=True)
    if remote.enabled():
        try:
            remote.image_put(name, (_dir() / name).read_bytes())
        except remote.RemoteError:
            (_dir() / name).unlink(missing_ok=True)
            raise
    small = img.copy()
    small.thumbnail((THUMB_SIDE, THUMB_SIDE))
    small.save(_dir() / _thumb_name(name), "JPEG", quality=80)
    return name


def image_path(name: str | None) -> Path | None:
    if not name:
        return None
    p = _dir() / name
    if p.exists():
        return p
    if remote.enabled() and name not in _missing:
        data = remote.image_get(name)
        if data:
            p.write_bytes(data)
            return p
        _missing.add(name)
    return None


def thumb_uri(name: str | None) -> str | None:
    """Tablolarda (ImageColumn) göstermek için küçük önizleme (data URI)."""
    if not name:
        return None
    p = _dir() / _thumb_name(name)
    if not p.exists():
        full = image_path(name)  # sunucu modunda gerekirse indirir
        if full is None:
            return None
        try:  # mobil uygulamadan yüklenen fotoğrafların önizlemesi ilk gösterimde üretilir
            img = ImageOps.exif_transpose(Image.open(full)).convert("RGB")
            img.thumbnail((THUMB_SIDE, THUMB_SIDE))
            img.save(p, "JPEG", quality=80)
        except Exception:
            return None
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def delete_image(name: str | None) -> None:
    if not name:
        return
    if remote.enabled():
        remote.image_delete(name)
    for n in (name, _thumb_name(name)):
        try:
            (_dir() / n).unlink()
        except OSError:
            pass
