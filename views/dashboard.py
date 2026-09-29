from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from core import db, metrics
from core.ui import badge, card_title, esc, info_rows, kpis, mini_table, nav_button, progress
from core.utils import MONTHS_SHORT, change_pct, dmy, money, num, prev_month_key, tr_lower


def _trend(p: float | None, suffix: str = "") -> tuple[str, str]:
    if p is None:
        return "", "flat"
    arrow = "↑" if p >= 0 else "↓"
    return f"{arrow} %{num(abs(p), 0)}{suffix}", "up" if p >= 0 else "down"


def _match(q: str, *vals) -> bool:
    return not q or tr_lower(q) in tr_lower(" ".join(str(v) for v in vals))


def render(q: str = "") -> None:
    cur = metrics.this_month()
    prev = prev_month_key(cur)

    product_count = db.scalar("SELECT COUNT(*) FROM products")
    new_products = db.scalar("SELECT COUNT(*) FROM products WHERE substr(created_at,1,7)=?", (cur,))
    sales_cur, sales_prev = metrics.sales_total(cur), metrics.sales_total(prev)
    net_cur, net_prev = metrics.net(cur), metrics.net(prev)
    stocks = db.stock_items(in_stock=True, with_products=True)
    critical = [s for s in stocks if s["status"] == "Kritik"]
    near = [s for s in stocks if s["status"] == "Minimuma Yakın"]

    s_ch, s_tr = _trend(change_pct(sales_cur, sales_prev))
    n_ch, n_tr = _trend(change_pct(net_cur, net_prev))
    kpis([
        {"icon": "◇", "color": "blue", "label": "Toplam Ürün", "value": num(product_count),
         "change": f"↑ {new_products} yeni" if new_products else "", "trend": "up"},
        {"icon": "₺", "color": "green", "label": "Bu Ay Satış", "value": money(sales_cur),
         "change": s_ch, "trend": s_tr},
        {"icon": "▤", "color": "purple", "label": "Net Kâr", "value": money(net_cur),
         "change": n_ch, "trend": n_tr},
        {"icon": "!", "color": "red", "label": "Kritik Stok", "value": num(len(critical)),
         "change": f"{len(near)} min. yakın" if near else "", "trend": "down"},
    ])

    if not product_count and not stocks and not db.scalar("SELECT COUNT(*) FROM customers"):
        st.info("👋 Veritabanı boş. Başlamak için sırasıyla **Stok** kalemlerini, **Ürünler**i "
                "(reçete ve operasyonlarıyla) ve **Müşteriler**i ekleyin; ardından **Satışlar** ve "
                "**Siparişler** oluşturabilirsiniz.")

    left, right = st.columns([1.5, 1])
    with left.container(key="card_dash_chart"):
        h1, h2 = st.columns([3, 1], vertical_alignment="center")
        with h1:
            card_title("Aylık Satışlar")
        years = metrics.years_with_data()
        year = h2.selectbox("Yıl", years, key="dash_year", label_visibility="collapsed")
        vals = metrics.monthly_sales(year)
        df = pd.DataFrame({"Ay": MONTHS_SHORT, "Satış": vals, "sira": range(12)})
        df["Etiket"] = df["Satış"].apply(money)
        chart = (
            alt.Chart(df)
            .mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, color="#1673d1", size=30)
            .encode(
                x=alt.X("Ay:N", sort=MONTHS_SHORT, title=None,
                        axis=alt.Axis(labelAngle=0, labelColor="#68768a", domain=False, ticks=False)),
                y=alt.Y("Satış:Q", title=None,
                        axis=alt.Axis(labelColor="#68768a", grid=True, gridColor="#edf1f5",
                                      domain=False, ticks=False, format="~s")),
                tooltip=[alt.Tooltip("Ay:N"), alt.Tooltip("Etiket:N", title="Satış")],
            )
            .properties(height=245)
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(chart, use_container_width=True)

    with right.container(key="card_dash_tx"):
        h1, h2 = st.columns([2, 1], vertical_alignment="center")
        with h1:
            card_title("Son İşlemler")
        with h2:
            nav_button("Tümünü Gör", "finance", "dash_tx_all")
        rows = []
        for t in db.query("SELECT * FROM transactions ORDER BY date DESC, id DESC LIMIT 25"):
            if not _match(q, t["description"], t["category"], t["doc_no"]):
                continue
            label = f"Satış #{t['doc_no']}" if t["sale_id"] else (t["description"] or t["category"])
            amt = money(t["amount"]) if t["type"] == "Gelir" else money(-t["amount"])
            cls = "income" if t["type"] == "Gelir" else "expense"
            rows.append([dmy(t["date"]), esc(label), f'<span class="{cls}">{amt}</span>'])
        mini_table(rows[:6], "Henüz işlem yok.")

    c1, c2, c3 = st.columns(3)
    with c1.container(key="card_dash_stock"):
        h1, h2 = st.columns([2, 1], vertical_alignment="center")
        with h1:
            card_title("Kritik Stoklar")
        with h2:
            nav_button("Stoka Git", "stock", "dash_stock")
        items = [s for s in critical + near if _match(q, s["name"], s["code"])]
        mini_table([[esc(s["name"]), f"{num(s['quantity'])} {esc(s['unit'])}", badge(s["status"])]
                    for s in items[:6]], "Kritik stok yok. 👍")

    with c2.container(key="card_dash_orders"):
        h1, h2 = st.columns([2, 1], vertical_alignment="center")
        with h1:
            card_title("Bekleyen Siparişler")
        with h2:
            nav_button("Tümünü Gör", "orders", "dash_orders")
        wos = [w for w in db.work_orders_list() if w["status"] in ("Bekliyor", "Üretimde")
               and _match(q, w["code"], w["product"], w["customer"])]
        mini_table([[esc(w["code"]), esc(w["product"]), f"{num(w['quantity'])} adet", badge(w["status"])]
                    for w in wos[:6]], "Bekleyen sipariş yok.")

    with c3.container(key="card_dash_cari"):
        h1, h2 = st.columns([2, 1], vertical_alignment="center")
        with h1:
            card_title("Cari Özet")
        with h2:
            nav_button("Müşteriler", "customers", "dash_cust")
        rec = metrics.receivables()
        over = metrics.overdue_receivables()
        total = float(db.scalar("SELECT COALESCE(SUM(amount),0) FROM sales"))
        paid = total - rec
        rate = paid / total * 100 if total else 0
        st.markdown(
            f'<div class="erp-klabel">Alacaklar</div><div class="erp-kvalue">{money(rec)}</div>'
            f'<div style="height:14px"></div><div class="erp-klabel">Vadesi Geçen</div>'
            f'<div class="expense">{money(over)}</div><div style="height:14px"></div>'
            f'<div class="erp-klabel">Tahsilat oranı: %{num(rate, 0)}</div>{progress(rate)}',
            unsafe_allow_html=True,
        )
