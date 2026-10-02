"""Merkezi sunucu (mobil uygulamanın kullandığı API) istemcisi.

Sunucu adresi: ortam değişkeni ERP_SERVER_URL ya da proje klasöründeki `server.txt` (ilk satır).
Adres yoksa uygulama eskisi gibi yerel SQLite ile çalışır.
Giriş: ERP_USER / ERP_PASS ortam değişkenleri varsa otomatik, yoksa uygulamadaki giriş formu."""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
_lock = threading.RLock()
_state = {"url": "", "token": "", "user": "", "password": ""}

# JSON'da `undefined` yok: sunucu {"__u": 1} işaretini undefined olarak yorumlar (isteğe bağlı id parametreleri için).
UNDEF = object()


class RemoteError(ValueError):
    """Sunucu / ağ hatası (kullanıcıya gösterilebilir Türkçe mesaj)."""


def _normalize(u: str) -> str:
    u = (u or "").strip().rstrip("/")
    if u and not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _load_url() -> str:
    u = os.environ.get("ERP_SERVER_URL", "")
    if not u:
        f = BASE_DIR / "server.txt"
        if f.exists():
            lines = f.read_text(encoding="utf-8").strip().splitlines()
            u = lines[0] if lines else ""
    return _normalize(u)


_state["url"] = _load_url()


def enabled() -> bool:
    return bool(_state["url"])


def server_url() -> str:
    return _state["url"]


def logged_in() -> bool:
    return bool(_state["token"])


def logout() -> None:
    with _lock:
        _state["token"] = _state["password"] = ""


def _request(path: str, payload=None, token: str | None = None, method: str = "POST",
             raw: bytes | None = None, ctype: str = "application/json", timeout: int = 60):
    url = _state["url"] + path
    data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", ctype)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RemoteError("Sunucuya ulaşılamadı. İnternet bağlantısını kontrol edin.") from e


def login(user: str, password: str) -> None:
    status, body = _request("/login", {"username": user.strip(), "password": password}, timeout=30)
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        data = {}
    if status != 200 or not data.get("token"):
        raise RemoteError(data.get("error") or f"Giriş başarısız ({status}).")
    with _lock:
        _state.update(token=data["token"], user=user.strip(), password=password)


def auto_login() -> bool:
    """ERP_USER / ERP_PASS ortam değişkenleri tanımlıysa giriş yapar."""
    u, p = os.environ.get("ERP_USER", ""), os.environ.get("ERP_PASS", "")
    if u and p:
        login(u, p)
        return True
    return False


def _enc(a):
    return {"__u": 1} if a is UNDEF else a


def batch(calls: list[tuple]) -> list:
    """[(repo, method, arg1, arg2, ...), ...] → sonuç listesi. Hata olursa RemoteError."""
    payload = [{"repo": c[0], "method": c[1], "args": [_enc(a) for a in c[2:]]} for c in calls]
    for attempt in (1, 2):
        with _lock:
            token = _state["token"]
        status, body = _request("/rpc", payload, token)
        if status == 401 and attempt == 1 and _state["user"] and _state["password"]:
            login(_state["user"], _state["password"])  # süresi dolmuş oturumu yenile
            continue
        break
    if status == 401:
        logout()
        raise RemoteError("Oturum süresi doldu, yeniden giriş yapın.")
    try:
        out = json.loads(body or b"[]")
    except ValueError:
        raise RemoteError(f"Sunucudan geçersiz yanıt ({status}).")
    if status != 200:
        raise RemoteError((out or {}).get("error", f"Sunucu hatası ({status}).") if isinstance(out, dict) else f"Sunucu hatası ({status}).")
    results = []
    for o in out:
        if o.get("error"):
            raise RemoteError(o["error"])
        results.append(o.get("result"))
    return results


def call(repo: str, method: str, *args):
    return batch([(repo, method, *args)])[0]


# ---------------------------------------------------------------- fotoğraflar
def image_get(name: str) -> bytes | None:
    status, body = _request(f"/images/{urllib.parse.quote(name)}?t={urllib.parse.quote(_state['token'])}", method="GET", timeout=60)
    return body if status == 200 else None


def image_put(name: str, data: bytes) -> None:
    status, body = _request(f"/images/{urllib.parse.quote(name)}", method="PUT", raw=data, ctype="image/jpeg",
                            token=_state["token"], timeout=120)
    if status != 200:
        raise RemoteError("Fotoğraf yüklenemedi.")


def image_delete(name: str) -> None:
    try:
        _request(f"/images/{urllib.parse.quote(name)}", method="DELETE", token=_state["token"], timeout=30)
    except RemoteError:
        pass
