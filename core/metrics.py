"""Dashboard, raporlar ve KPI kartları için hesaplamalar."""
from __future__ import annotations

from datetime import date

from core import db
from core.utils import month_key


def this_month() -> str:
    return month_key(date.today())


def sales_total(month: str | None = None, year: str | None = None, status: str | None = None) -> float:
    sql, p = "SELECT COALESCE(SUM(amount),0) FROM sales WHERE 1=1", []
    if month:
        sql += " AND substr(date,1,7)=?"; p.append(month)
    if year:
        sql += " AND substr(date,1,4)=?"; p.append(year)
    if status:
        sql += " AND status=?"; p.append(status)
    return float(db.scalar(sql, p))


def sales_count(month: str) -> int:
    return int(db.scalar("SELECT COUNT(*) FROM sales WHERE substr(date,1,7)=?", (month,)))


def tx_total(kind: str, month: str | None = None, year: str | None = None,
             categories: list[str] | None = None, exclude: list[str] | None = None) -> float:
    sql, p = "SELECT COALESCE(SUM(amount),0) FROM transactions WHERE type=?", [kind]
    if month:
        sql += " AND substr(date,1,7)=?"; p.append(month)
    if year:
        sql += " AND substr(date,1,4)=?"; p.append(year)
    if categories:
        sql += f" AND category IN ({','.join('?' * len(categories))})"; p += categories
    if exclude:
        sql += f" AND category NOT IN ({','.join('?' * len(exclude))})"; p += exclude
    return float(db.scalar(sql, p))


def net(month: str | None = None, year: str | None = None) -> float:
    return tx_total("Gelir", month, year) - tx_total("Gider", month, year)


def monthly_sales(year: str) -> list[float]:
    rows = db.query("SELECT substr(date,6,2) AS m, SUM(amount) AS t FROM sales "
                    "WHERE substr(date,1,4)=? GROUP BY m", (year,))
    vals = [0.0] * 12
    for r in rows:
        vals[int(r["m"]) - 1] = float(r["t"] or 0)
    return vals


def years_with_data() -> list[str]:
    ys = {str(date.today().year)}
    for r in db.query("SELECT DISTINCT substr(date,1,4) AS y FROM sales "
                      "UNION SELECT DISTINCT substr(date,1,4) FROM transactions"):
        if r["y"]:
            ys.add(r["y"])
    return sorted(ys, reverse=True)


def months_with_data() -> list[str]:
    ms = {this_month()}
    for r in db.query("SELECT DISTINCT substr(date,1,7) AS m FROM transactions "
                      "UNION SELECT DISTINCT substr(date,1,7) FROM sales"):
        if r["m"]:
            ms.add(r["m"])
    return sorted(ms, reverse=True)


def receivables() -> float:
    return float(db.scalar("SELECT COALESCE(SUM(amount),0) FROM sales WHERE status='Bekliyor'"))


def overdue_receivables() -> float:
    return float(db.scalar("SELECT COALESCE(SUM(amount),0) FROM sales WHERE status='Bekliyor' "
                           "AND due_date IS NOT NULL AND due_date < date('now','localtime')"))


def production_hours(month: str) -> float:
    """Ay içinde gerçekleşen üretim saati: o ay tamamlanan siparişlerin tamamı +
    halen üretimdeki siparişlerin ilerleme oranı kadarı."""
    rows = db.query(
        """SELECT w.quantity, w.progress, w.status, w.completed_at,
                  (SELECT COALESCE(SUM(minutes),0) FROM product_operations o WHERE o.product_id=w.product_id) AS mins
           FROM work_orders w WHERE w.status IN ('Tamamlandı','Üretimde')"""
    )
    total = 0.0
    for r in rows:
        if r["status"] == "Tamamlandı" and (r["completed_at"] or "")[:7] == month:
            total += r["quantity"] * r["mins"]
        elif r["status"] == "Üretimde":
            total += r["quantity"] * r["mins"] * r["progress"] / 100
    return total / 60


def stock_value() -> float:
    return float(db.scalar("SELECT COALESCE(SUM(quantity*unit_cost),0) FROM stock_items"))


def stock_turnover(year: str) -> float:
    """Yıllık satılan ürünlerin reçete malzeme maliyeti / mevcut stok değeri
    (yılın geçen kısmına göre yıllıklandırılır)."""
    cogs = float(db.scalar(
        """SELECT COALESCE(SUM(s.quantity * (
                SELECT COALESCE(SUM(m.quantity*si.unit_cost),0) FROM product_materials m
                JOIN stock_items si ON si.id=m.stock_id WHERE m.product_id=s.product_id)),0)
           FROM sales s WHERE substr(s.date,1,4)=?""", (year,)))
    sv = stock_value()
    if sv <= 0 or cogs <= 0:
        return 0.0
    today = date.today()
    if str(today.year) == year:
        factor = 365 / max(1, (today - date(today.year, 1, 1)).days + 1)
    else:
        factor = 1
    return cogs * factor / sv


def top_products(year: str, limit: int | None = None) -> list[dict]:
    sql = """SELECT p.code, p.name, SUM(s.quantity) AS qty, SUM(s.amount) AS revenue
             FROM sales s JOIN products p ON p.id=s.product_id
             WHERE substr(s.date,1,4)=? GROUP BY p.id ORDER BY revenue DESC"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.query(sql, (year,))


def monthly_summary(year: str) -> list[dict]:
    out = []
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        inc = tx_total("Gelir", key)
        prod = tx_total("Gider", key, categories=["Malzeme", "Bakım", "Enerji"])
        pers = tx_total("Gider", key, categories=["Personel"])
        other = tx_total("Gider", key, exclude=["Malzeme", "Bakım", "Enerji", "Personel"])
        out.append({"month": key, "sales": sales_total(month=key), "income": inc,
                    "production": prod, "personnel": pers, "other": other,
                    "net": inc - prod - pers - other})
    return out
