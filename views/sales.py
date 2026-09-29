from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import db, metrics
from core.ui import bump, card_title, confirm_delete, data_table, flash, kpis, search_filter
from core.utils import dmy, month_label, money, num, to_date


@st.dialog("Satış", width="medium")
def sale_dialog(s: dict | None = None) -> None:
    s = s or {}
    customers = db.query("SELECT id, name, status FROM customers ORDER BY name")
    products = db.query("SELECT id, name, code, unit_price, status FROM products ORDER BY name")
    if not customers or not products:
        st.warning("Satış girmek için en az bir **müşteri** ve bir **ürün** tanımlı olmalı.")
        return
    tax_rate = float(db.get_setting("tax_rate") or 0)

    cmap = {c["id"]: c["name"] + (" · Pasif" if c["status"] == "Pasif" else "") for c in customers}
    cids = list(cmap)
    cid = st.selectbox("Müşteri *", cids, index=cids.index(s["customer_id"]) if s.get("customer_id") in cids else 0,
                       format_func=cmap.get)
    pmap = {p["id"]: f"{p['name']} ({p['code']})" for p in products}
    pids = list(pmap)
    pid = st.selectbox("Ürün *", pids, index=pids.index(s["product_id"]) if s.get("product_id") in pids else 0,
                       format_func=pmap.get, key="sale_pid")
    list_price = next(p["unit_price"] for p in products if p["id"] == pid)

    c1, c2 = st.columns(2)
    qty = c1.number_input("Adet *", min_value=1.0, value=float(s.get("quantity", 1)), step=1.0)
    same_product = bool(s) and pid == s.get("product_id")
    price_default = float(s["unit_price"]) if same_product else float(list_price)
    price = c2.number_input("Birim Fiyat (KDV hariç)", min_value=0.0, value=price_default, step=10.0,
                            key=f"sale_price_{pid}")
    add_tax = st.checkbox(f"KDV ekle (%{num(tax_rate)})", value=not bool(s))
    subtotal = qty * price
    total = subtotal * (1 + tax_rate / 100) if add_tax else subtotal
    st.markdown(f"Ara toplam: **{money(subtotal)}**" + (f" · KDV: **{money(total - subtotal)}**" if add_tax else "")
                + f" · Toplam: **{money(total)}**")
    unchanged = same_product and qty == float(s["quantity"]) and price == float(s["unit_price"]) and not add_tax
    amount = st.number_input("Tutar", min_value=0.0,
                             value=float(s["amount"]) if unchanged else round(total, 2), step=10.0,
                             key=f"sale_amount_{pid}_{qty}_{price}_{add_tax}",
                             help="Hesaplanan toplam; gerekirse elle değiştirebilirsiniz (iskonto vb.).")
    c3, c4, c5 = st.columns(3)
    sdate = c3.date_input("Tarih", value=to_date(s.get("date")) or date.today(), format="DD.MM.YYYY")
    due = c4.date_input("Vade", value=to_date(s.get("due_date")) or sdate + timedelta(days=30), format="DD.MM.YYYY")
    status = c5.selectbox("Durum", db.SALE_STATUSES,
                          index=db.SALE_STATUSES.index(s["status"]) if s.get("status") in db.SALE_STATUSES else 0)
    paid = None
    if status == "Ödendi":
        paid = st.date_input("Tahsilat Tarihi", value=to_date(s.get("paid_date")) or date.today(), format="DD.MM.YYYY")
        st.caption("💡 Tahsil edilen satış, Gelir / Gider'e otomatik gelir kaydı olarak yazılır.")
    note = st.text_input("Not", value=s.get("note") or "")

    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch", disabled=amount <= 0):
        data = {"date": sdate.isoformat(), "customer_id": cid, "product_id": pid, "quantity": qty,
                "unit_price": price, "amount": amount, "status": status, "due_date": due.isoformat(),
                "paid_date": paid.isoformat() if paid else None, "note": note.strip()}
        db.save_sale(data, s.get("id"))
        flash("Satış kaydedildi.")
        bump("sales")
        st.rerun()


@st.dialog("Tahsilat")
def collect_dialog(s: dict) -> None:
    st.markdown(f"**{s['code']}** · {s['customer'] or '-'} — **{money(s['amount'])}**")
    on = st.date_input("Tahsilat Tarihi", value=date.today(), format="DD.MM.YYYY")
    st.caption("Kaydedildiğinde satış 'Ödendi' olur ve Gelir / Gider'e gelir kaydı eklenir.")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Tahsil Et", type="primary", width="stretch"):
        db.mark_sale_paid(s["id"], on.isoformat())
        flash(f"{s['code']} tahsil edildi: {money(s['amount'])}")
        bump("sales")
        st.rerun()


def render(q: str = "") -> None:
    months = metrics.months_with_data()
    rows = db.sales_list()
    kpi_box = st.container()  # KPI'lar filtrelere göre aşağıda doldurulur

    with st.container(key="card_sales"):
        h = st.columns([1.8, 1.8, 1.4, 1.5, 1.3], vertical_alignment="center")
        with h[0]:
            card_title("Satışlar")
        local = h[1].text_input("Satış ara", placeholder="Satış ara...", label_visibility="collapsed", key="sale_q")
        stf = h[2].selectbox("Durum", ["Tüm Durumlar", "Ödendi", "Bekliyor", "Vadesi Geçen"],
                             label_visibility="collapsed", key="sale_st")
        month = h[3].selectbox("Dönem", ["Tüm Dönemler"] + months, index=1 + months.index(metrics.this_month()), format_func=
                               lambda m: m if m == "Tüm Dönemler" else month_label(m),
                               label_visibility="collapsed", key="sale_month")
        if h[4].button("＋ Yeni Satış", type="primary", width="stretch"):
            sale_dialog()

        km = None if month == "Tüm Dönemler" else month
        today = date.today().isoformat()
        df = pd.DataFrame(rows)
        if not df.empty:
            if km:
                df = df[df["date"].str[:7] == km]
            df["Durum"] = df.apply(lambda r: "Gecikti" if r["status"] == "Bekliyor" and r["due_date"]
                                   and r["due_date"] < today else r["status"], axis=1)
            if stf == "Vadesi Geçen":
                df = df[df["Durum"] == "Gecikti"]
            elif stf != "Tüm Durumlar":
                df = df[df["status"] == stf]
            df["Tarih"] = df["date"].apply(dmy)
            df["Vade"] = df["due_date"].apply(dmy)
            df = df.rename(columns={"code": "Satış No", "customer": "Müşteri", "product": "Ürün",
                                    "quantity": "Adet", "unit_price": "Birim Fiyat", "amount": "Tutar"})
            df = search_filter(df, local, q)
        sel = data_table(df, "sales",
                         ["Satış No", "Tarih", "Müşteri", "Ürün", "Adet", "Birim Fiyat", "Tutar", "Vade", "Durum"],
                         status_cols=("Durum",), money_cols=("Birim Fiyat", "Tutar"),
                         column_config={"Adet": st.column_config.NumberColumn(format="%g")},
                         title="Satışlar")
        if not rows:
            st.caption("İlk satışı girmek için **＋ Yeni Satış** butonunu kullanın.")
        elif sel is None:
            st.caption("Tahsilat, düzenleme veya silme için tablodan bir satış seçin.")

    # KPI'lar seçili döneme göre (varsayılan: bu ay)
    total = metrics.sales_total(month=km)
    paid = metrics.sales_total(month=km, status="Ödendi")
    count = len([r for r in rows if km is None or r["date"][:7] == km])
    lbl = "Toplam Satış" if km is None else ("Bu Ay" if km == metrics.this_month() else month_label(km))
    with kpi_box:
        kpis([
            {"icon": "₺", "color": "green", "label": lbl, "value": money(total)},
            {"icon": "#", "color": "blue", "label": "Fatura / Satış", "value": num(count)},
            {"icon": "✓", "color": "purple", "label": "Tahsil Edilen", "value": money(paid)},
            {"icon": "!", "color": "red", "label": "Bekleyen", "value": money(total - paid)},
        ])

    if sel is None:
        return
    s = next((r for r in rows if r["id"] == sel), None)
    if not s:
        return
    with st.container(key="card_sale_actions"):
        card_title(f"{s['code']} · {s['customer'] or '-'} · {money(s['amount'])}")
        b = st.columns([1.2, 1.2, 1, 1, 2])
        if s["status"] == "Bekliyor":
            if b[0].button("✓ Tahsil Et", type="primary", width="stretch"):
                collect_dialog(s)
        else:
            if b[0].button("↺ Tahsilatı Geri Al", width="stretch"):
                data = dict(s)
                data["status"] = "Bekliyor"
                db.save_sale(data, s["id"])
                flash(f"{s['code']} tekrar 'Bekliyor' durumuna alındı; gelir kaydı kaldırıldı.", "↺")
                bump("sales")
                st.rerun()
        if b[1].button("✎ Düzenle", width="stretch"):
            sale_dialog(s)
        with b[2]:
            def _del():
                db.delete_sale(s["id"])
                bump("sales")
            confirm_delete(f"sale_{s['id']}", s["code"], _del)
        st.caption(f"Tarih: {dmy(s['date'])} · Vade: {dmy(s['due_date'])} · Ürün: {s['product'] or '-'} × "
                   f"{num(s['quantity'])} · Tahsilat: {dmy(s['paid_date'])}" + (f" · Not: {s['note']}" if s.get("note") else ""))
