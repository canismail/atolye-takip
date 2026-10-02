"""Veritabanı katmanı: SQLite şema, sorgu yardımcıları, ayarlar, yedekleme
ve kayıtlar arası otomatik bağlantılar (ör. tahsil edilen satış -> gelir kaydı)."""
from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import threading
import time
from datetime import date, datetime
from pathlib import Path

from core import remote

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "erp.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS stock_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    category   TEXT NOT NULL DEFAULT 'Hammadde',
    unit       TEXT NOT NULL DEFAULT 'adet',
    quantity   REAL NOT NULL DEFAULT 0,
    min_qty    REAL NOT NULL DEFAULT 0,
    unit_cost  REAL NOT NULL DEFAULT 0,
    location   TEXT,
    created_at TEXT NOT NULL DEFAULT (date('now','localtime')),
    shape       TEXT,                    -- Hammadde ölçüsü: 'rect' | 'round' | 'pipe'
    dim_a       REAL,                    -- en (rect) veya çap (round) veya dış çap (pipe), mm
    dim_b       REAL,                    -- boy (rect) veya et kalınlığı (pipe), mm
    length_mm   REAL,                    -- uzunluk, mm
    grade       TEXT,                    -- malzeme cinsi (ör. 1040)
    density     REAL,                    -- g/cm³
    unit_weight REAL NOT NULL DEFAULT 0, -- parça başına kg (hesaplanan)
    kg_price    REAL,                    -- hammadde kg fiyatı
    in_stock    INTEGER NOT NULL DEFAULT 0, -- 1: Stok sayfasında takip ediliyor
    product_id  INTEGER,                    -- dolu ise bu satır bir ürünün (mamul) stoğudur
    image       TEXT                        -- fotoğraf dosya adı (data/images)
);

CREATE TABLE IF NOT EXISTS stock_movements (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    stock_id  INTEGER NOT NULL REFERENCES stock_items(id) ON DELETE CASCADE,
    date      TEXT NOT NULL,
    change    REAL NOT NULL,          -- giriş +, çıkış -
    note      TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT 'Metal Ürün',
    icon        TEXT NOT NULL DEFAULT '📦',
    unit_price  REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'Aktif',
    description TEXT,
    created_at  TEXT NOT NULL DEFAULT (date('now','localtime')),
    image       TEXT                       -- fotoğraf dosya adı (data/images)
);

CREATE TABLE IF NOT EXISTS product_materials (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    stock_id   INTEGER NOT NULL REFERENCES stock_items(id),
    quantity   REAL NOT NULL DEFAULT 1,
    seq        INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS product_operations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    seq        INTEGER NOT NULL DEFAULT 1,
    name       TEXT NOT NULL,
    minutes    REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    code       TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    contact    TEXT,
    phone      TEXT,
    email      TEXT,
    address    TEXT,
    tax_no     TEXT,
    status     TEXT NOT NULL DEFAULT 'Aktif',
    created_at TEXT NOT NULL DEFAULT (date('now','localtime'))
);

CREATE TABLE IF NOT EXISTS sales (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE NOT NULL,
    date        TEXT NOT NULL,
    customer_id INTEGER REFERENCES customers(id),
    product_id  INTEGER REFERENCES products(id),
    quantity    REAL NOT NULL DEFAULT 1,
    unit_price  REAL NOT NULL DEFAULT 0,
    amount      REAL NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'Bekliyor',   -- Ödendi / Bekliyor
    due_date    TEXT,
    paid_date   TEXT,
    note        TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('Gelir','Gider')),
    category    TEXT NOT NULL DEFAULT 'Diğer',
    description TEXT,
    doc_no      TEXT,
    amount      REAL NOT NULL DEFAULT 0,        -- her zaman pozitif
    sale_id     INTEGER REFERENCES sales(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS work_orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT UNIQUE NOT NULL,
    customer_id  INTEGER REFERENCES customers(id),
    product_id   INTEGER NOT NULL REFERENCES products(id),
    quantity     REAL NOT NULL DEFAULT 1,
    due_date     TEXT,
    progress     INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'Bekliyor',  -- Bekliyor/Üretimde/Tamamlandı/İptal
    note         TEXT,
    created_at   TEXT NOT NULL DEFAULT (date('now','localtime')),
    completed_at TEXT
);
"""

DEFAULT_SETTINGS = {
    "company_name": "CMS Teknik Mühendislik",
    "company_phone": "",
    "company_email": "",
    "company_address": "",
    "company_tax_office": "",
    "company_tax_no": "",
    "user_name": "Can Meral",
    "currency": "TRY",
    "tax_rate": "20",
    "stock_alert": "1",
    "near_min_pct": "20",
    "auto_backup": "1",
    "backup_keep": "10",
    "last_backup": "",
    "sales_target": "300000",
    "capacity_hours": "300",
    "turnover_target": "6",
    "plan_daily_hours": "8",
    "plan_week_days": "5",
    "plan_buffer_pct": "15",
    "plan_workers": "1",
    "material_types": json.dumps([
        {"name": "1040 (Çelik)", "density": 7.85},
        {"name": "1050 (Çelik)", "density": 7.85},
        {"name": "St37 (Çelik)", "density": 7.85},
        {"name": "Paslanmaz 304", "density": 7.93},
        {"name": "Alüminyum", "density": 2.70},
        {"name": "Pirinç", "density": 8.50},
        {"name": "Bakır", "density": 8.96},
        {"name": "Döküm", "density": 7.20},
    ], ensure_ascii=False),
}

STOCK_CATEGORIES = ["Yedek Parça", "Hammadde", "Diğer"]
DEFAULT_DENSITY = 7.85  # çelik / demir, g/cm³
STOCK_MIGRATIONS = [
    ("shape", "TEXT"), ("dim_a", "REAL"), ("dim_b", "REAL"), ("length_mm", "REAL"),
    ("grade", "TEXT"), ("density", "REAL"), ("unit_weight", "REAL NOT NULL DEFAULT 0"),
    ("kg_price", "REAL"), ("in_stock", "INTEGER NOT NULL DEFAULT 0"), ("product_id", "INTEGER"), ("image", "TEXT"),
]
PRODUCT_MIGRATIONS = [("image", "TEXT")]
UNITS = ["adet", "kg", "gr", "lt", "metre", "paket", "takım"]
PRODUCT_CATEGORIES = ["Metal Ürün", "Yedek Parça", "Makine", "Diğer"]
INCOME_CATEGORIES = ["Satış", "Hizmet", "Faiz", "Diğer Gelir"]
EXPENSE_CATEGORIES = ["Malzeme", "Kira", "Personel", "Enerji", "Bakım", "Vergi", "Nakliye", "Diğer Gider"]
ORDER_STATUSES = ["Bekliyor", "Üretimde", "Tamamlandı", "İptal"]
SALE_STATUSES = ["Bekliyor", "Ödendi"]



# ---------------------------------------------------------------- sunucu modu (mobil uygulamayla ortak veritabanı)
# Sunucu adresi tanımlıysa (core/remote.py) okumalar sunucudan alınan bir anlık görüntü (bellek içi SQLite) üzerinden,
# yazmalar ise sunucudaki servis çağrılarıyla yapılır. Böylece telefon ve bilgisayar aynı veriyi kullanır.
BACKUP_TABLES = ["settings", "customers", "products", "stock_items", "stock_movements",
                 "product_materials", "product_operations", "sales", "transactions", "work_orders"]
SNAP_TTL = 6  # sn: başka cihazlardaki değişiklikler en geç bu kadar sonra görünür
_snap: dict = {"conn": None, "ts": 0.0, "dirty": True}
_snap_lock = threading.RLock()
_read_lock = threading.RLock()


def _build_snapshot(tables: dict) -> sqlite3.Connection:
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    _init_schema(c)
    for t in reversed(BACKUP_TABLES):
        c.execute(f"DELETE FROM {t}")
    for t in BACKUP_TABLES:
        for row in tables.get(t) or []:
            cols = list(row)
            if cols:
                c.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                          [row[k] for k in cols])
    c.commit()
    return c


def refresh(force: bool = False) -> None:
    """Sunucudaki verinin anlık görüntüsünü yeniler (kirliyse ya da SNAP_TTL geçtiyse)."""
    with _snap_lock:
        fresh = _snap["conn"] is not None and not _snap["dirty"] and time.time() - _snap["ts"] < SNAP_TTL
        if fresh and not force:
            return
        data = remote.call("backup", "exportAll")
        old = _snap["conn"]
        _snap.update(conn=_build_snapshot(data["tables"]), ts=time.time(), dirty=False)
        if old is not None:
            try:
                old.close()
            except sqlite3.Error:
                pass


def begin_run() -> None:
    """Her Streamlit çalışmasının başında çağrılır."""
    if remote.enabled():
        refresh()


def _rpc(repo: str, method: str, *args):
    r = remote.call(repo, method, *args)
    _snap["dirty"] = True
    return r


def _opt(v):
    return remote.UNDEF if v is None else v


# ---------------------------------------------------------------- bağlantı
def get_conn() -> sqlite3.Connection:
    if remote.enabled():
        if _snap["conn"] is None or _snap["dirty"]:
            refresh(force=True)
        return _snap["conn"]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    if remote.enabled():
        refresh(force=True)
        return
    with get_conn() as c:
        _init_schema(c)
        _seed_material_type(c, "1050 (Çelik)", 7.85, "seed_mt_1050")


def _seed_material_type(c: sqlite3.Connection, name: str, density: float, flag: str) -> None:
    """Var olan veritabanlarına yeni bir malzeme cinsini bir kez ekler (kullanıcı sonradan silerse geri gelmez)."""
    if c.execute("SELECT 1 FROM settings WHERE key=?", (flag,)).fetchone():
        return
    row = c.execute("SELECT value FROM settings WHERE key='material_types'").fetchone()
    try:
        rows = json.loads(row[0]) if row and row[0] else []
    except ValueError:
        rows = []
    if not any(str(r.get("name", "")).startswith(name.split()[0]) for r in rows):
        idx = next((i for i, r in enumerate(rows) if str(r.get("name", "")).startswith("1040")), len(rows) - 1)
        rows.insert(idx + 1, {"name": name, "density": density})
        c.execute("INSERT INTO settings(key, value) VALUES ('material_types', ?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(rows, ensure_ascii=False),))
    c.execute("INSERT INTO settings(key, value) VALUES (?, '1')", (flag,))


def _init_schema(c: sqlite3.Connection) -> None:
    if True:
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(stock_items)")}
        for col, ddl in STOCK_MIGRATIONS:
            if col not in have:
                c.execute(f"ALTER TABLE stock_items ADD COLUMN {col} {ddl}")
                if col == "in_stock":  # eski kayıtlar zaten stokta görünüyordu
                    c.execute("UPDATE stock_items SET in_stock=1")
        have_p = {r[1] for r in c.execute("PRAGMA table_info(products)")}
        for col, ddl in PRODUCT_MIGRATIONS:
            if col not in have_p:
                c.execute(f"ALTER TABLE products ADD COLUMN {col} {ddl}")
        # eski kategoriler (Sarf, Kimyasal, Yarı Mamul...) yeni listeye taşınır
        marks = ",".join("?" * len(STOCK_CATEGORIES))
        c.execute(f"UPDATE stock_items SET category='Diğer' WHERE product_id IS NULL AND category NOT IN ({marks})",
                  STOCK_CATEGORIES)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    with _read_lock, get_conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: tuple | list = (), default=0):
    with _read_lock, get_conn() as c:
        r = c.execute(sql, params).fetchone()
    if r is None or r[0] is None:
        return default
    return r[0]


def execute(sql: str, params: tuple | list = ()) -> int:
    if remote.enabled():
        raise RuntimeError("Sunucu modunda doğrudan SQL yazılamaz; ilgili db fonksiyonunu kullanın.")
    with get_conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def today() -> str:
    return date.today().isoformat()


# ---------------------------------------------------------------- ayarlar
def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    for r in query("SELECT key, value FROM settings"):
        s[r["key"]] = r["value"]
    return s


def get_setting(key: str, default: str = "") -> str:
    v = scalar("SELECT value FROM settings WHERE key=?", (key,), None)
    return DEFAULT_SETTINGS.get(key, default) if v is None else v


def set_settings(values: dict) -> None:
    if remote.enabled():
        _rpc("settings", "set", {k: str(v) for k, v in values.items()})
        return
    with get_conn() as c:
        for k, v in values.items():
            c.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )


# ---------------------------------------------------------------- kodlar
def next_code(table: str, prefix: str, width: int = 3, start: int = 1) -> str:
    """Tablodaki `prefix` ile başlayan en büyük numaralı kodun bir fazlası."""
    rows = query(f"SELECT code FROM {table} WHERE code LIKE ?", (prefix + "%",))
    nums = []
    for r in rows:
        tail = r["code"][len(prefix):]
        if tail.isdigit():
            nums.append(int(tail))
    n = max(nums) + 1 if nums else start
    return f"{prefix}{n:0{width}d}"


def code_from_name(table: str, name: str, digits: int = 2) -> str:
    """İsimden okunabilir bir kod üretir: adın ilk kelimesinin baş harfleri + sıra no
    (ör. 'Masa Ayağı' -> 'MASA-01'). Aynı kökten kod varsa numarayla ayrılır."""
    import re

    from core.utils import tr_ascii

    words = re.findall(r"[A-Za-z0-9]+", tr_ascii(name or "").upper())
    root = (words[0][:6] if words else "GEN") or "GEN"
    existing = {r["code"] for r in query(f"SELECT code FROM {table} WHERE code LIKE ?", (root + "%",))}
    n = 1
    while f"{root}-{n:0{digits}d}" in existing:
        n += 1
    return f"{root}-{n:0{digits}d}"


# ---------------------------------------------------------------- stok
def stock_status(qty: float, min_qty: float, near_pct: float) -> str:
    if min_qty > 0 and qty < min_qty:
        return "Kritik"
    if min_qty > 0 and qty <= min_qty * (1 + near_pct / 100):
        return "Minimuma Yakın"
    return "Normal"


def calc_volume_cm3(shape: str | None, a: float, b: float, length: float) -> float:
    """Hacim (cm³). Ölçüler mm.
    rect: en × boy × uzunluk · round: π/4 × çap² × uzunluk ·
    pipe (boru): π/4 × (dış çap² − iç çap²) × uzunluk = π × et × (dış çap − et) × uzunluk, iç çap = dış çap − 2 × et.
    Boruda et kalınlığı 0'dan büyük ve dış çapın yarısından fazla olamaz (geçersizse 0)."""
    import math

    if not shape or not length or not a:
        return 0.0
    if shape == "round":
        vol_mm3 = math.pi / 4 * a * a * length
    elif shape == "pipe":
        t = b or 0
        if t <= 0 or 2 * t > a:
            return 0.0
        vol_mm3 = math.pi * t * (a - t) * length
    else:
        vol_mm3 = a * (b or 0) * length
    return vol_mm3 / 1000  # mm³ → cm³


def calc_unit_weight(shape: str | None, a: float, b: float, length: float, density: float) -> float:
    """Parça başına kg. Ölçüler mm, yoğunluk g/cm³ (hacim için calc_volume_cm3)."""
    if not density:
        return 0.0
    return calc_volume_cm3(shape, a, b, length) * density / 1000  # cm³ → g → kg


def get_material_types() -> list[dict]:
    """Ayarlardaki malzeme cinsi / yoğunluk (g/cm³) listesi."""
    try:
        rows = json.loads(get_setting("material_types") or "[]")
    except ValueError:
        rows = []
    return [{"name": str(r["name"]), "density": float(r["density"])}
            for r in rows if r.get("name") and float(r.get("density") or 0) > 0]


def set_material_types(rows: list[dict]) -> None:
    if remote.enabled():
        _rpc("settings", "setMaterialTypes", rows)
        return
    set_settings({"material_types": json.dumps(rows, ensure_ascii=False)})


def material_density(grade: str | None, fallback: float = DEFAULT_DENSITY) -> float:
    for r in get_material_types():
        if r["name"] == grade:
            return r["density"]
    return fallback


def hammadde_unit_cost(unit: str, weight: float, kg_price: float) -> float:
    """Birim maliyet: ölçülü hammaddede parça ağırlığı × kg fiyatı, ölçü yoksa kg fiyatı."""
    return weight * kg_price if weight > 0 else kg_price


def recalc_hammadde() -> int:
    """Ayarlardaki yoğunluklar değişince tüm hammaddelerin ağırlık ve maliyetini yeniden hesaplar."""
    if remote.enabled():
        return int(_rpc("stock", "recalcHammadde"))
    n = 0
    with get_conn() as c:
        for r in c.execute("SELECT * FROM stock_items WHERE category='Hammadde' AND shape IS NOT NULL").fetchall():
            dens = material_density(r["grade"], r["density"] or DEFAULT_DENSITY)
            w = calc_unit_weight(r["shape"], r["dim_a"] or 0, r["dim_b"] or 0, r["length_mm"] or 0, dens)
            cost = r["unit_cost"] if r["kg_price"] is None else hammadde_unit_cost(r["unit"], w, r["kg_price"])
            unit = "adet" if w > 0 and r["kg_price"] is not None else r["unit"]  # ölçülü hammadde parça olarak takip edilir
            c.execute("UPDATE stock_items SET density=?, unit_weight=?, unit_cost=?, unit=? WHERE id=?",
                      (dens, w, cost, unit, r["id"]))
            n += 1
    return n


def size_label(r: dict) -> str:
    """Hammadde ölçüsünü okunur yazıya çevirir: '30x40 x 50 mm' / 'Ø30 x 50 mm' / 'Boru Ø40x3 x 500 mm'."""
    if not r.get("shape") or not r.get("length_mm"):
        return ""
    a, b, ln = r.get("dim_a") or 0, r.get("dim_b") or 0, r["length_mm"]
    from core.utils import num

    if r["shape"] == "round":
        return f"Ø{num(a)} x {num(ln)} mm"
    if r["shape"] == "pipe":
        return f"Boru Ø{num(a)}x{num(b)} x {num(ln)} mm"
    return f"{num(a)}x{num(b)} x {num(ln)} mm"


def stock_items(in_stock: bool = False, with_products: bool = False) -> list[dict]:
    """Malzeme bileşenleri. in_stock=True: sadece Stok sayfasına eklenmiş olanlar.
    with_products=True: ürünlerin (mamul) stok satırları da dahil."""
    near = float(get_setting("near_min_pct") or 20)
    where = []
    if in_stock:
        where.append("s.in_stock=1")
    if not with_products:
        where.append("s.product_id IS NULL")
    rows = query("SELECT s.*, COALESCE(s.image, p.image) AS photo FROM stock_items s "
                 "LEFT JOIN products p ON p.id=s.product_id"
                 + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY s.code")
    for r in rows:
        r["status"] = stock_status(r["quantity"], r["min_qty"], near)
        r["value"] = r["quantity"] * r["unit_cost"]
        r["size"] = size_label(r)
    return rows


def add_stock_movement(stock_id: int, change: float, note: str = "", on: str | None = None) -> None:
    if remote.enabled():
        _rpc("stock", "addMovement", stock_id, change, note, on or remote.UNDEF)
        return
    with get_conn() as c:
        c.execute("UPDATE stock_items SET quantity = quantity + ? WHERE id=?", (change, stock_id))
        c.execute(
            "INSERT INTO stock_movements(stock_id, date, change, note) VALUES (?,?,?,?)",
            (stock_id, on or today(), change, note),
        )


def add_to_stock(stock_id: int, qty: float = 0, note: str = "", on: str | None = None) -> None:
    """Bileşeni Stok sayfasına ekler; başlangıç miktarı varsa giriş hareketi yazar."""
    if remote.enabled():
        _rpc("stock", "addToStock", stock_id, qty, note, on or remote.UNDEF)
        return
    execute("UPDATE stock_items SET in_stock=1 WHERE id=?", (stock_id,))
    if qty:
        add_stock_movement(stock_id, qty, note or "İlk stok girişi", on)


def add_product_to_stock(product_id: int, qty: float = 0, note: str = "", on: str | None = None) -> int:
    """Ürünü (mamul) Stok sayfasına ekler; stok satırı yoksa oluşturur. Birim maliyet = malzeme maliyeti."""
    if remote.enabled():
        return int(_rpc("stock", "addProductToStock", product_id, qty, note, on or remote.UNDEF))
    p = next((x for x in products_with_stats() if x["id"] == product_id), None)
    if p is None:
        raise ValueError("Ürün bulunamadı.")
    row = one("SELECT id FROM stock_items WHERE product_id=?", (product_id,))
    if row:
        sid = row["id"]
        execute("UPDATE stock_items SET in_stock=1, name=?, unit_cost=? WHERE id=?",
                (p["name"], p["material_cost"] or 0, sid))
    else:
        sid = execute("INSERT INTO stock_items(code, name, category, unit, quantity, min_qty, unit_cost, "
                      "in_stock, product_id) VALUES (?,?,?,?,0,0,?,1,?)",
                      ("URN-" + p["code"], p["name"], "Ürün", "adet", p["material_cost"] or 0, product_id))
    if qty:
        add_stock_movement(sid, qty, note or "İlk stok girişi", on)
    return sid


def remove_from_stock(stock_id: int) -> str | None:
    if remote.enabled():
        return _rpc("stock", "removeFromStock", stock_id)
    q = scalar("SELECT quantity FROM stock_items WHERE id=?", (stock_id,))
    if q:
        return "Stokta miktar var. Önce stok hareketiyle miktarı sıfırlayın."
    execute("UPDATE stock_items SET in_stock=0 WHERE id=?", (stock_id,))
    return None


def delete_stock_item(stock_id: int) -> str | None:
    if remote.enabled():
        r = _rpc("stock", "remove", stock_id)
        if r.get("removedImage"):
            from core import images
            images.delete_image(r["removedImage"])
        return r.get("error")
    used = scalar("SELECT COUNT(*) FROM product_materials WHERE stock_id=?", (stock_id,))
    if used:
        return f"Bu kalem {used} ürün reçetesinde kullanılıyor. Önce reçetelerden çıkarın."
    img = scalar("SELECT image FROM stock_items WHERE id=?", (stock_id,), None)
    execute("DELETE FROM stock_items WHERE id=?", (stock_id,))
    if img:
        from core import images
        images.delete_image(img)
    return None


# ---------------------------------------------------------------- ürünler
def products_with_stats() -> list[dict]:
    return query(
        """
        SELECT p.*,
          (SELECT COUNT(*) FROM product_materials m WHERE m.product_id=p.id) AS material_count,
          (SELECT COUNT(*) FROM product_operations o WHERE o.product_id=p.id) AS operation_count,
          (SELECT COALESCE(SUM(o.minutes),0) FROM product_operations o WHERE o.product_id=p.id) AS total_minutes,
          (SELECT COALESCE(SUM(m.quantity*s.unit_cost),0) FROM product_materials m
              JOIN stock_items s ON s.id=m.stock_id WHERE m.product_id=p.id) AS material_cost
        FROM products p ORDER BY p.code
        """
    )


def product_materials(product_id: int) -> list[dict]:
    return query(
        """SELECT m.id, m.seq, m.quantity, s.code, s.name, s.unit, s.unit_cost,
                  m.quantity*s.unit_cost AS cost, s.id AS stock_id
           FROM product_materials m JOIN stock_items s ON s.id=m.stock_id
           WHERE m.product_id=? ORDER BY m.seq, m.id""",
        (product_id,),
    )


def product_operations(product_id: int) -> list[dict]:
    return query(
        "SELECT * FROM product_operations WHERE product_id=? ORDER BY seq, id", (product_id,)
    )


def renumber(table: str, product_id: int) -> None:
    if remote.enabled():
        return  # sunucu sıralamayı taşıma/silme sırasında kendisi düzenler
    rows = query(f"SELECT id FROM {table} WHERE product_id=? ORDER BY seq, id", (product_id,))
    with get_conn() as c:
        for i, r in enumerate(rows, start=1):
            c.execute(f"UPDATE {table} SET seq=? WHERE id=?", (i, r["id"]))


def move_row(table: str, product_id: int, row_id: int, direction: int) -> None:
    """direction: -1 yukarı, +1 aşağı"""
    if remote.enabled():
        _rpc("products", "moveRow", table, product_id, row_id, direction)
        return
    renumber(table, product_id)
    rows = query(f"SELECT id, seq FROM {table} WHERE product_id=? ORDER BY seq", (product_id,))
    ids = [r["id"] for r in rows]
    if row_id not in ids:
        return
    i = ids.index(row_id)
    j = i + direction
    if j < 0 or j >= len(ids):
        return
    ids[i], ids[j] = ids[j], ids[i]
    with get_conn() as c:
        for k, rid in enumerate(ids, start=1):
            c.execute(f"UPDATE {table} SET seq=? WHERE id=?", (k, rid))


def delete_product(product_id: int) -> str | None:
    if remote.enabled():
        r = _rpc("products", "remove", product_id)
        if r.get("removedImage"):
            from core import images
            images.delete_image(r["removedImage"])
        return r.get("error")
    s = scalar("SELECT COUNT(*) FROM sales WHERE product_id=?", (product_id,))
    w = scalar("SELECT COUNT(*) FROM work_orders WHERE product_id=?", (product_id,))
    if s or w:
        return (f"Bu ürüne bağlı {s} satış ve {w} sipariş var; silinemez. "
                "Kullanımdan kaldırmak için durumunu 'Pasif' yapabilirsiniz.")
    img = scalar("SELECT image FROM products WHERE id=?", (product_id,), None)
    with get_conn() as c:
        c.execute("DELETE FROM stock_items WHERE product_id=?", (product_id,))
        c.execute("DELETE FROM products WHERE id=?", (product_id,))
    if img:
        from core import images
        images.delete_image(img)
    return None


# ---------------------------------------------------------------- müşteriler
def customers_with_stats() -> list[dict]:
    return query(
        """
        SELECT c.*,
          (SELECT COALESCE(SUM(amount),0) FROM sales s WHERE s.customer_id=c.id) AS total_sales,
          (SELECT COALESCE(SUM(amount),0) FROM sales s WHERE s.customer_id=c.id AND s.status='Bekliyor') AS balance,
          (SELECT COALESCE(SUM(amount),0) FROM sales s WHERE s.customer_id=c.id AND s.status='Bekliyor'
                AND s.due_date IS NOT NULL AND s.due_date < date('now','localtime')) AS overdue
        FROM customers c ORDER BY c.code
        """
    )


def delete_customer(customer_id: int) -> str | None:
    if remote.enabled():
        return _rpc("customers", "remove", customer_id)
    s = scalar("SELECT COUNT(*) FROM sales WHERE customer_id=?", (customer_id,))
    w = scalar("SELECT COUNT(*) FROM work_orders WHERE customer_id=?", (customer_id,))
    if s or w:
        return (f"Bu müşteriye bağlı {s} satış ve {w} sipariş var; silinemez. "
                "Durumunu 'Pasif' yapabilirsiniz.")
    execute("DELETE FROM customers WHERE id=?", (customer_id,))
    return None


# ---------------------------------------------------------------- satışlar
def sales_list() -> list[dict]:
    return query(
        """SELECT s.*, c.name AS customer, p.name AS product
           FROM sales s
           LEFT JOIN customers c ON c.id=s.customer_id
           LEFT JOIN products p ON p.id=s.product_id
           ORDER BY s.date DESC, s.id DESC"""
    )


def _sync_sale_income(c: sqlite3.Connection, sale_id: int) -> None:
    """Satış 'Ödendi' ise ona bağlı tek bir gelir kaydı olmasını sağlar,
    'Bekliyor' ise bağlı gelir kaydını kaldırır."""
    s = c.execute(
        """SELECT s.*, p.name AS product FROM sales s
           LEFT JOIN products p ON p.id=s.product_id WHERE s.id=?""",
        (sale_id,),
    ).fetchone()
    if s is None:
        return
    existing = c.execute("SELECT id FROM transactions WHERE sale_id=?", (sale_id,)).fetchone()
    if s["status"] == "Ödendi":
        desc = f"{s['product'] or 'Ürün'} satışı"
        paid = s["paid_date"] or s["date"]
        if existing:
            c.execute(
                "UPDATE transactions SET date=?, amount=?, description=?, doc_no=? WHERE id=?",
                (paid, s["amount"], desc, s["code"], existing["id"]),
            )
        else:
            c.execute(
                """INSERT INTO transactions(date, type, category, description, doc_no, amount, sale_id)
                   VALUES (?, 'Gelir', 'Satış', ?, ?, ?, ?)""",
                (paid, desc, s["code"], s["amount"], sale_id),
            )
    elif existing:
        c.execute("DELETE FROM transactions WHERE id=?", (existing["id"],))


def save_sale(data: dict, sale_id: int | None = None) -> int:
    if remote.enabled():
        keys = ["date", "customer_id", "product_id", "quantity", "unit_price", "amount",
                "status", "due_date", "paid_date", "note"]
        return int(_rpc("sales", "save", {k: data.get(k) for k in keys}, _opt(sale_id)))
    fields = ["date", "customer_id", "product_id", "quantity", "unit_price", "amount",
              "status", "due_date", "paid_date", "note"]
    if data.get("status") == "Ödendi" and not data.get("paid_date"):
        data["paid_date"] = today()
    if data.get("status") != "Ödendi":
        data["paid_date"] = None
    with get_conn() as c:
        if sale_id is None:
            code = data.get("code") or next_code("sales", "S-", 4, 1001)
            cur = c.execute(
                f"INSERT INTO sales(code, {', '.join(fields)}) VALUES (?{', ?' * len(fields)})",
                [code] + [data.get(f) for f in fields],
            )
            sale_id = cur.lastrowid
        else:
            c.execute(
                f"UPDATE sales SET {', '.join(f + '=?' for f in fields)} WHERE id=?",
                [data.get(f) for f in fields] + [sale_id],
            )
        _sync_sale_income(c, sale_id)
    return sale_id


def mark_sale_paid(sale_id: int, paid_on: str | None = None) -> None:
    if remote.enabled():
        _rpc("sales", "markPaid", sale_id, paid_on or remote.UNDEF)
        return
    with get_conn() as c:
        c.execute("UPDATE sales SET status='Ödendi', paid_date=? WHERE id=?",
                  (paid_on or today(), sale_id))
        _sync_sale_income(c, sale_id)


def delete_sale(sale_id: int) -> None:
    if remote.enabled():
        _rpc("sales", "remove", sale_id)
        return
    with get_conn() as c:
        c.execute("DELETE FROM transactions WHERE sale_id=?", (sale_id,))
        c.execute("DELETE FROM sales WHERE id=?", (sale_id,))


# ---------------------------------------------------------------- siparişler
def work_orders_list() -> list[dict]:
    return query(
        """SELECT w.*, c.name AS customer, p.name AS product,
                  (SELECT COALESCE(SUM(o.minutes),0) FROM product_operations o WHERE o.product_id=w.product_id) AS unit_minutes
           FROM work_orders w
           LEFT JOIN customers c ON c.id=w.customer_id
           LEFT JOIN products p ON p.id=w.product_id
           ORDER BY CASE w.status WHEN 'Tamamlandı' THEN 2 WHEN 'İptal' THEN 3 ELSE 1 END,
                    w.due_date, w.id"""
    )


def status_for_progress(progress: int, current: str) -> str:
    if current == "İptal":
        return "İptal"
    if progress >= 100:
        return "Tamamlandı"
    if progress > 0:
        return "Üretimde"
    return "Bekliyor"


def save_work_order(data: dict, wo_id: int | None = None) -> int:
    if remote.enabled():
        keys = ["customer_id", "product_id", "quantity", "due_date", "progress", "status", "note", "completed_at"]
        return int(_rpc("orders", "save", {k: data.get(k) for k in keys}, _opt(wo_id)))
    status = data.get("status", "Bekliyor")
    progress = int(data.get("progress", 0))
    if status == "Tamamlandı":
        progress = 100
    data["progress"] = progress
    data["completed_at"] = (data.get("completed_at") or today()) if status == "Tamamlandı" else None
    fields = ["customer_id", "product_id", "quantity", "due_date", "progress", "status", "note", "completed_at"]
    if wo_id is None:
        code = next_code("work_orders", "SIP-", 4, 1001)
        return execute(
            f"INSERT INTO work_orders(code, {', '.join(fields)}) VALUES (?{', ?' * len(fields)})",
            [code] + [data.get(f) for f in fields],
        )
    execute(f"UPDATE work_orders SET {', '.join(f + '=?' for f in fields)} WHERE id=?",
            [data.get(f) for f in fields] + [wo_id])
    return wo_id


def update_progress(wo_id: int, progress: int) -> None:
    if remote.enabled():
        _rpc("orders", "updateProgress", wo_id, progress)
        return
    w = one("SELECT status, completed_at FROM work_orders WHERE id=?", (wo_id,))
    if not w:
        return
    status = status_for_progress(progress, w["status"])
    completed = (w["completed_at"] or today()) if status == "Tamamlandı" else None
    execute("UPDATE work_orders SET progress=?, status=?, completed_at=? WHERE id=?",
            (progress, status, completed, wo_id))


# ---------------------------------------------------------------- kayıt fonksiyonları (görünümler bunları kullanır)
def save_customer(v: dict, customer_id: int | None = None) -> int:
    """v: name, contact, phone, email, address, tax_no, status"""
    if remote.enabled():
        keys = ["name", "contact", "phone", "email", "address", "tax_no", "status"]
        return int(_rpc("customers", "save", {k: (v.get(k) or "") for k in keys}, _opt(customer_id)))
    vals = (v["name"].strip(), v.get("contact", ""), v.get("phone", ""), v.get("email", ""), v.get("address", ""),
            v.get("tax_no", ""), v.get("status", "Aktif"))
    if customer_id is not None:
        execute("UPDATE customers SET name=?, contact=?, phone=?, email=?, address=?, tax_no=?, status=? WHERE id=?",
                vals + (customer_id,))
        return customer_id
    code = code_from_name("customers", v["name"])
    return execute("INSERT INTO customers(code, name, contact, phone, email, address, tax_no, status) "
                   "VALUES (?,?,?,?,?,?,?,?)", (code,) + vals)


def set_customer_status(customer_id: int, status: str) -> None:
    if remote.enabled():
        _rpc("customers", "setStatus", customer_id, status)
        return
    execute("UPDATE customers SET status=? WHERE id=?", (status, customer_id))


def save_transaction(v: dict, tx_id: int | None = None) -> int:
    """v: date, type, category, description, doc_no, amount"""
    if remote.enabled():
        keys = ["date", "type", "category", "description", "doc_no", "amount"]
        return int(_rpc("sales", "saveTransaction", {k: v.get(k) for k in keys}, _opt(tx_id)))
    vals = (v["date"], v["type"], v.get("category") or "Diğer", v.get("description", ""), v.get("doc_no", ""), v["amount"])
    if tx_id is not None:
        execute("UPDATE transactions SET date=?, type=?, category=?, description=?, doc_no=?, amount=? WHERE id=?",
                vals + (tx_id,))
        return tx_id
    return execute("INSERT INTO transactions(date, type, category, description, doc_no, amount) "
                   "VALUES (?,?,?,?,?,?)", vals)


def delete_transaction(tx_id: int) -> None:
    if remote.enabled():
        _rpc("sales", "removeTransaction", tx_id)
        return
    execute("DELETE FROM transactions WHERE id=?", (tx_id,))


def save_material(v: dict, item_id: int | None = None) -> int:
    """Malzeme bileşeni. v: name, category, unit, min_qty, unit_cost, shape, dim_a, dim_b, length_mm, grade,
    density, unit_weight, kg_price, image  (hammadde dışında ölçü alanları None)."""
    if remote.enabled():
        keys = ["name", "category", "unit", "min_qty", "unit_cost", "shape", "dim_a", "dim_b", "length_mm",
                "grade", "kg_price", "image"]
        return int(_rpc("stock", "saveMaterial", {k: v.get(k) for k in keys}, _opt(item_id)))
    extra = (v.get("shape"), v.get("dim_a"), v.get("dim_b"), v.get("length_mm"), v.get("grade"),
             v.get("density"), v.get("unit_weight") or 0.0, v.get("kg_price"))
    if item_id is not None:
        execute("UPDATE stock_items SET name=?, category=?, unit=?, min_qty=?, unit_cost=?, "
                "shape=?, dim_a=?, dim_b=?, length_mm=?, grade=?, density=?, unit_weight=?, kg_price=?, image=? "
                "WHERE id=?", (v["name"].strip(), v["category"], v["unit"], v["min_qty"], v["unit_cost"], *extra,
                               v.get("image"), item_id))
        return item_id
    code = code_from_name("stock_items", v["name"])
    return execute("INSERT INTO stock_items(code, name, category, unit, quantity, min_qty, unit_cost, "
                   "shape, dim_a, dim_b, length_mm, grade, density, unit_weight, kg_price, image) "
                   "VALUES (?,?,?,?,0,?,?,?,?,?,?,?,?,?,?,?)",
                   (code, v["name"].strip(), v["category"], v["unit"], v["min_qty"], v["unit_cost"], *extra,
                    v.get("image")))


def save_product(v: dict, product_id: int | None = None) -> int:
    """v: name, category, icon, unit_price, status, description, image"""
    if remote.enabled():
        keys = ["name", "category", "icon", "unit_price", "status", "description", "image"]
        d = {k: v.get(k) for k in keys}
        d["description"] = d["description"] or ""
        return int(_rpc("products", "save", d, _opt(product_id)))
    vals = (v["name"].strip(), v.get("category") or "Diğer", v.get("icon") or "📦", v["unit_price"], v["status"],
            (v.get("description") or "").strip(), v.get("image"))
    if product_id is not None:
        execute("UPDATE products SET name=?, category=?, icon=?, unit_price=?, status=?, "
                "description=?, image=? WHERE id=?", vals + (product_id,))
        return product_id
    code = code_from_name("products", v["name"])
    return execute("INSERT INTO products(code, name, category, icon, unit_price, status, description, image) "
                   "VALUES (?,?,?,?,?,?,?,?)", (code,) + vals)


def save_product_material(product_id: int, stock_id: int, qty: float, row_id: int | None = None) -> None:
    """Reçeteye bileşen ekler (aynı bileşen varsa miktar eklenir) ya da satırın miktarını günceller."""
    if remote.enabled():
        _rpc("products", "saveMaterialRow", product_id, stock_id, qty, _opt(row_id))
        return
    if row_id is not None:
        execute("UPDATE product_materials SET quantity=? WHERE id=?", (qty, row_id))
        return
    dup = one("SELECT id FROM product_materials WHERE product_id=? AND stock_id=?", (product_id, stock_id))
    if dup:
        execute("UPDATE product_materials SET quantity=quantity+? WHERE id=?", (qty, dup["id"]))
    else:
        seq = scalar("SELECT COALESCE(MAX(seq),0)+1 FROM product_materials WHERE product_id=?", (product_id,))
        execute("INSERT INTO product_materials(product_id, stock_id, quantity, seq) VALUES (?,?,?,?)",
                (product_id, stock_id, qty, seq))


def save_operation(product_id: int, name: str, minutes: float, row_id: int | None = None) -> None:
    if remote.enabled():
        _rpc("products", "saveOperation", product_id, name.strip(), minutes, _opt(row_id))
        return
    if row_id is not None:
        execute("UPDATE product_operations SET name=?, minutes=? WHERE id=?", (name.strip(), minutes, row_id))
        return
    seq = scalar("SELECT COALESCE(MAX(seq),0)+1 FROM product_operations WHERE product_id=?", (product_id,))
    execute("INSERT INTO product_operations(product_id, seq, name, minutes) VALUES (?,?,?,?)",
            (product_id, seq, name.strip(), minutes))


def delete_row(table: str, product_id: int, row_id: int) -> None:
    """Reçete / operasyon satırını siler ve sıra numaralarını düzenler."""
    if remote.enabled():
        _rpc("products", "removeRow", table, product_id, row_id)
        return
    execute(f"DELETE FROM {table} WHERE id=?", (row_id,))
    renumber(table, product_id)


def delete_order(wo_id: int) -> None:
    if remote.enabled():
        _rpc("orders", "remove", wo_id)
        return
    execute("DELETE FROM work_orders WHERE id=?", (wo_id,))


def cancel_order(wo_id: int) -> None:
    if remote.enabled():
        _rpc("orders", "cancel", wo_id)
        return
    execute("UPDATE work_orders SET status='İptal' WHERE id=?", (wo_id,))


def reopen_order(wo_id: int, progress: int) -> None:
    if remote.enabled():
        _rpc("orders", "reopen", wo_id)
        return
    execute("UPDATE work_orders SET status=? WHERE id=?", (status_for_progress(progress, "Bekliyor"), wo_id))


# ---------------------------------------------------------------- yedekleme
def backup_now(tag: str = "manuel") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"erp_{stamp}_{tag}.db"
    # Sunucu modunda yedek, sunucudaki verinin yerel bir .db kopyasıdır.
    src = get_conn() if remote.enabled() else sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with _read_lock, dst:
        src.backup(dst)
    if not remote.enabled():
        src.close()
    dst.close()
    set_settings({"last_backup": datetime.now().strftime("%Y-%m-%d %H:%M")})
    prune_backups()
    return target


def prune_backups() -> None:
    keep = int(get_setting("backup_keep") or 10)
    files = sorted(BACKUP_DIR.glob("erp_*.db"), reverse=True)
    for f in files[keep:]:
        try:
            f.unlink()
        except OSError:
            pass


def list_backups() -> list[Path]:
    if not BACKUP_DIR.exists():
        return []
    return sorted(BACKUP_DIR.glob("erp_*.db"), reverse=True)


def auto_backup_if_due() -> None:
    """Otomatik yedekleme açıksa günde bir kez yedek alır."""
    if get_setting("auto_backup") != "1":
        return
    last = get_setting("last_backup")
    if last and last[:10] == today():
        return
    if not remote.enabled() and not DB_PATH.exists():
        return
    backup_now("otomatik")


def _backup_json_from_sqlite(path: Path) -> dict:
    """SQLite dosyasını sunucunun içe aktarma biçimine (JSON) çevirir."""
    src = sqlite3.connect(path)
    src.row_factory = sqlite3.Row
    try:
        have = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        tables = {t: [dict(r) for r in src.execute(f"SELECT * FROM {t}")] for t in BACKUP_TABLES if t in have}
    finally:
        src.close()
    return {"app": "atolye-yonetim", "version": 1, "exported_at": datetime.now().isoformat(), "tables": tables}


def restore_backup(path: Path) -> None:
    backup_now("geri-yukleme-oncesi")
    if remote.enabled():
        _rpc("backup", "importAll", _backup_json_from_sqlite(path))
        return
    shutil.copyfile(path, DB_PATH)
    init_db()


def restore_from_bytes(data: bytes) -> None:
    if not data.startswith(b"SQLite format 3"):
        raise ValueError("Geçerli bir SQLite yedek dosyası değil.")
    backup_now("geri-yukleme-oncesi")
    if remote.enabled():
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "yuklenen.db"
            tmp.write_bytes(data)
            _rpc("backup", "importAll", _backup_json_from_sqlite(tmp))
        return
    DB_PATH.write_bytes(data)
    init_db()


def db_bytes() -> bytes | None:
    """Veritabanının indirilebilir bir .db kopyası (sunucu modunda anlık görüntüden üretilir)."""
    if remote.enabled():
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d) / "kopya.db"
            dst = sqlite3.connect(tmp)
            with _read_lock, dst:
                get_conn().backup(dst)
            dst.close()
            return tmp.read_bytes()
    return DB_PATH.read_bytes() if DB_PATH.exists() else None


def reset_all_data() -> None:
    if remote.enabled():
        backup_now("sifirlama-oncesi")
        _rpc("backup", "resetAll")
        from core import images
        images.clear_cache()
        return
    backup_now("sifirlama-oncesi")
    with get_conn() as c:
        for t in ["transactions", "sales", "work_orders", "product_materials", "product_operations",
                  "products", "stock_movements", "stock_items", "customers"]:
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")
    imgs = DATA_DIR / "images"
    if imgs.exists():
        for f in imgs.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
