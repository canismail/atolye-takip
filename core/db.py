"""Veritabanı katmanı: SQLite şema, sorgu yardımcıları, ayarlar, yedekleme
ve kayıtlar arası otomatik bağlantılar (ör. tahsil edilen satış -> gelir kaydı)."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

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
    shape       TEXT,                    -- Hammadde ölçüsü: 'rect' | 'round'
    dim_a       REAL,                    -- en (rect) veya çap (round), mm
    dim_b       REAL,                    -- boy (rect), mm
    length_mm   REAL,                    -- uzunluk, mm
    grade       TEXT,                    -- malzeme cinsi (ör. 1040)
    density     REAL,                    -- g/cm³
    unit_weight REAL NOT NULL DEFAULT 0, -- parça başına kg (hesaplanan)
    kg_price    REAL,                    -- hammadde kg fiyatı
    in_stock    INTEGER NOT NULL DEFAULT 0, -- 1: Stok sayfasında takip ediliyor
    product_id  INTEGER                     -- dolu ise bu satır bir ürünün (mamul) stoğudur
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
    created_at  TEXT NOT NULL DEFAULT (date('now','localtime'))
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
    "material_types": json.dumps([
        {"name": "1040 (Çelik)", "density": 7.85},
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
    ("kg_price", "REAL"), ("in_stock", "INTEGER NOT NULL DEFAULT 0"), ("product_id", "INTEGER"),
]
UNITS = ["adet", "kg", "gr", "lt", "metre", "paket", "takım"]
PRODUCT_CATEGORIES = ["Metal Ürün", "Yedek Parça", "Makine", "Diğer"]
INCOME_CATEGORIES = ["Satış", "Hizmet", "Faiz", "Diğer Gelir"]
EXPENSE_CATEGORIES = ["Malzeme", "Kira", "Personel", "Enerji", "Bakım", "Vergi", "Nakliye", "Diğer Gider"]
ORDER_STATUSES = ["Bekliyor", "Üretimde", "Tamamlandı", "İptal"]
SALE_STATUSES = ["Bekliyor", "Ödendi"]


# ---------------------------------------------------------------- bağlantı
def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_conn() as c:
        c.executescript(SCHEMA)
        have = {r[1] for r in c.execute("PRAGMA table_info(stock_items)")}
        for col, ddl in STOCK_MIGRATIONS:
            if col not in have:
                c.execute(f"ALTER TABLE stock_items ADD COLUMN {col} {ddl}")
                if col == "in_stock":  # eski kayıtlar zaten stokta görünüyordu
                    c.execute("UPDATE stock_items SET in_stock=1")
        # eski kategoriler (Sarf, Kimyasal, Yarı Mamul...) yeni listeye taşınır
        marks = ",".join("?" * len(STOCK_CATEGORIES))
        c.execute(f"UPDATE stock_items SET category='Diğer' WHERE product_id IS NULL AND category NOT IN ({marks})",
                  STOCK_CATEGORIES)
        for k, v in DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, v))


def query(sql: str, params: tuple | list = ()) -> list[dict]:
    with get_conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql: str, params: tuple | list = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def scalar(sql: str, params: tuple | list = (), default=0):
    with get_conn() as c:
        r = c.execute(sql, params).fetchone()
    if r is None or r[0] is None:
        return default
    return r[0]


def execute(sql: str, params: tuple | list = ()) -> int:
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


def calc_unit_weight(shape: str | None, a: float, b: float, length: float, density: float) -> float:
    """Parça başına kg. Ölçüler mm, yoğunluk g/cm³.
    rect: en × boy × uzunluk, round: π/4 × çap² × uzunluk."""
    import math

    if not shape or not length or not density or not a:
        return 0.0
    if shape == "round":
        vol_mm3 = math.pi / 4 * a * a * length
    else:
        vol_mm3 = a * (b or 0) * length
    return vol_mm3 / 1000 * density / 1000  # mm³ → cm³ → g → kg


def get_material_types() -> list[dict]:
    """Ayarlardaki malzeme cinsi / yoğunluk (g/cm³) listesi."""
    try:
        rows = json.loads(get_setting("material_types") or "[]")
    except ValueError:
        rows = []
    return [{"name": str(r["name"]), "density": float(r["density"])}
            for r in rows if r.get("name") and float(r.get("density") or 0) > 0]


def set_material_types(rows: list[dict]) -> None:
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
    """Hammadde ölçüsünü okunur yazıya çevirir: '30x40 x 50 mm' / 'Ø30 x 50 mm'."""
    if not r.get("shape") or not r.get("length_mm"):
        return ""
    a, b, ln = r.get("dim_a") or 0, r.get("dim_b") or 0, r["length_mm"]
    from core.utils import num

    if r["shape"] == "round":
        return f"Ø{num(a)} x {num(ln)} mm"
    return f"{num(a)}x{num(b)} x {num(ln)} mm"


def stock_items(in_stock: bool = False, with_products: bool = False) -> list[dict]:
    """Malzeme bileşenleri. in_stock=True: sadece Stok sayfasına eklenmiş olanlar.
    with_products=True: ürünlerin (mamul) stok satırları da dahil."""
    near = float(get_setting("near_min_pct") or 20)
    where = []
    if in_stock:
        where.append("in_stock=1")
    if not with_products:
        where.append("product_id IS NULL")
    rows = query("SELECT * FROM stock_items" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY code")
    for r in rows:
        r["status"] = stock_status(r["quantity"], r["min_qty"], near)
        r["value"] = r["quantity"] * r["unit_cost"]
        r["size"] = size_label(r)
    return rows


def add_stock_movement(stock_id: int, change: float, note: str = "", on: str | None = None) -> None:
    with get_conn() as c:
        c.execute("UPDATE stock_items SET quantity = quantity + ? WHERE id=?", (change, stock_id))
        c.execute(
            "INSERT INTO stock_movements(stock_id, date, change, note) VALUES (?,?,?,?)",
            (stock_id, on or today(), change, note),
        )


def add_to_stock(stock_id: int, qty: float = 0, note: str = "", on: str | None = None) -> None:
    """Bileşeni Stok sayfasına ekler; başlangıç miktarı varsa giriş hareketi yazar."""
    execute("UPDATE stock_items SET in_stock=1 WHERE id=?", (stock_id,))
    if qty:
        add_stock_movement(stock_id, qty, note or "İlk stok girişi", on)


def add_product_to_stock(product_id: int, qty: float = 0, note: str = "", on: str | None = None) -> int:
    """Ürünü (mamul) Stok sayfasına ekler; stok satırı yoksa oluşturur. Birim maliyet = malzeme maliyeti."""
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
    q = scalar("SELECT quantity FROM stock_items WHERE id=?", (stock_id,))
    if q:
        return "Stokta miktar var. Önce stok hareketiyle miktarı sıfırlayın."
    execute("UPDATE stock_items SET in_stock=0 WHERE id=?", (stock_id,))
    return None


def delete_stock_item(stock_id: int) -> str | None:
    used = scalar("SELECT COUNT(*) FROM product_materials WHERE stock_id=?", (stock_id,))
    if used:
        return f"Bu kalem {used} ürün reçetesinde kullanılıyor. Önce reçetelerden çıkarın."
    execute("DELETE FROM stock_items WHERE id=?", (stock_id,))
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
    rows = query(f"SELECT id FROM {table} WHERE product_id=? ORDER BY seq, id", (product_id,))
    with get_conn() as c:
        for i, r in enumerate(rows, start=1):
            c.execute(f"UPDATE {table} SET seq=? WHERE id=?", (i, r["id"]))


def move_row(table: str, product_id: int, row_id: int, direction: int) -> None:
    """direction: -1 yukarı, +1 aşağı"""
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
    s = scalar("SELECT COUNT(*) FROM sales WHERE product_id=?", (product_id,))
    w = scalar("SELECT COUNT(*) FROM work_orders WHERE product_id=?", (product_id,))
    if s or w:
        return (f"Bu ürüne bağlı {s} satış ve {w} sipariş var; silinemez. "
                "Kullanımdan kaldırmak için durumunu 'Pasif' yapabilirsiniz.")
    with get_conn() as c:
        c.execute("DELETE FROM stock_items WHERE product_id=?", (product_id,))
        c.execute("DELETE FROM products WHERE id=?", (product_id,))
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
    with get_conn() as c:
        c.execute("UPDATE sales SET status='Ödendi', paid_date=? WHERE id=?",
                  (paid_on or today(), sale_id))
        _sync_sale_income(c, sale_id)


def delete_sale(sale_id: int) -> None:
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
    w = one("SELECT status, completed_at FROM work_orders WHERE id=?", (wo_id,))
    if not w:
        return
    status = status_for_progress(progress, w["status"])
    completed = (w["completed_at"] or today()) if status == "Tamamlandı" else None
    execute("UPDATE work_orders SET progress=?, status=?, completed_at=? WHERE id=?",
            (progress, status, completed, wo_id))


# ---------------------------------------------------------------- yedekleme
def backup_now(tag: str = "manuel") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"erp_{stamp}_{tag}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(target)
    with dst:
        src.backup(dst)
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
    if not DB_PATH.exists():
        return
    backup_now("otomatik")


def restore_backup(path: Path) -> None:
    backup_now("geri-yukleme-oncesi")
    shutil.copyfile(path, DB_PATH)
    init_db()


def restore_from_bytes(data: bytes) -> None:
    if not data.startswith(b"SQLite format 3"):
        raise ValueError("Geçerli bir SQLite yedek dosyası değil.")
    backup_now("geri-yukleme-oncesi")
    DB_PATH.write_bytes(data)
    init_db()


def reset_all_data() -> None:
    backup_now("sifirlama-oncesi")
    with get_conn() as c:
        for t in ["transactions", "sales", "work_orders", "product_materials", "product_operations",
                  "products", "stock_movements", "stock_items", "customers"]:
            c.execute(f"DELETE FROM {t}")
        c.execute("DELETE FROM sqlite_sequence")
