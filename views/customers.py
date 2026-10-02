from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db, metrics
from core.ui import bump, card_title, confirm_delete, data_table, esc, flash, kpis, search_filter
from core.utils import dmy, initials, money, num


@st.dialog("Müşteri")
def customer_dialog(c: dict | None = None) -> None:
    c = c or {}
    name = st.text_input("Firma / Müşteri Adı *", value=c.get("name", ""), placeholder="Örn. ABC Metal San.")
    if c:
        st.caption(f"Kod: **{c['code']}**")
    elif name.strip():
        st.caption(f"Kod: **{db.code_from_name('customers', name)}**  _(isme göre otomatik oluşturulur)_")
    else:
        st.caption("Kod: müşteri adını yazınca otomatik oluşturulur.")
    c3, c4 = st.columns(2)
    contact = c3.text_input("Yetkili", value=c.get("contact") or "")
    phone = c4.text_input("Telefon", value=c.get("phone") or "", placeholder="0532 000 00 00")
    c5, c6 = st.columns(2)
    email = c5.text_input("E-posta", value=c.get("email") or "")
    tax = c6.text_input("Vergi No", value=c.get("tax_no") or "")
    addr = st.text_area("Adres", value=c.get("address") or "", height=70)
    status = st.radio("Durum", ["Aktif", "Pasif"], index=1 if c.get("status") == "Pasif" else 0, horizontal=True)
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        if not name.strip():
            st.error("Müşteri adı zorunludur.")
            return
        if email and "@" not in email:
            st.error("E-posta adresi geçersiz görünüyor.")
            return
        vals = {"name": name.strip(), "contact": contact.strip(), "phone": phone.strip(), "email": email.strip(),
                "address": addr.strip(), "tax_no": tax.strip(), "status": status}
        if c:
            db.save_customer(vals, c["id"])
            flash(f"{name} güncellendi.")
        else:
            db.save_customer(vals)
            flash(f"{name} eklendi.")
        bump("customers")
        st.rerun()


def render(q: str = "") -> None:
    rows = db.customers_with_stats()
    kpis([
        {"icon": "♙", "color": "blue", "label": "Toplam Müşteri", "value": num(len(rows))},
        {"icon": "₺", "color": "green", "label": "Toplam Alacak", "value": money(metrics.receivables())},
        {"icon": "!", "color": "red", "label": "Vadesi Geçen", "value": money(metrics.overdue_receivables())},
        {"icon": "★", "color": "purple", "label": "Aktif Müşteri",
         "value": num(sum(1 for r in rows if r["status"] == "Aktif"))},
    ])

    with st.container(key="card_customers"):
        h = st.columns([2.4, 2, 1.5, 1.4], vertical_alignment="center")
        with h[0]:
            card_title("Müşteri Listesi")
        local = h[1].text_input("Müşteri ara", placeholder="Müşteri ara...", label_visibility="collapsed", key="cust_q")
        stf = h[2].selectbox("Durum", ["Tüm Durumlar", "Aktif", "Pasif", "Bakiyesi Olan"],
                             label_visibility="collapsed", key="cust_st")
        if h[3].button("＋ Yeni Müşteri", type="primary", width="stretch"):
            customer_dialog()
        df = pd.DataFrame(rows)
        if not df.empty:
            if stf in ("Aktif", "Pasif"):
                df = df[df["status"] == stf]
            elif stf == "Bakiyesi Olan":
                df = df[df["balance"] > 0]
            df["Bakiye"] = df["balance"]
            df = df.rename(columns={"code": "Kod", "name": "Müşteri", "contact": "Yetkili", "phone": "Telefon",
                                    "email": "E-posta", "total_sales": "Toplam Satış", "status": "Durum"})
            df = search_filter(df, local, q)
        sel = data_table(df, "customers",
                         ["Kod", "Müşteri", "Yetkili", "Telefon", "E-posta", "Toplam Satış", "Bakiye", "Durum"],
                         status_cols=("Durum",), money_cols=("Toplam Satış",), debt_cols=("Bakiye",),
                         title="Müşteri Listesi")
        if not rows:
            st.caption("İlk müşteriyi eklemek için **＋ Yeni Müşteri** butonunu kullanın.")
        elif sel is None:
            st.caption("Detay ve işlemler için tablodan bir müşteri seçin.")

    if sel is None:
        return
    c = next((r for r in rows if r["id"] == sel), None)
    if not c:
        return
    with st.container(key="card_customer_detail"):
        top, acts = st.columns([2, 1.6], vertical_alignment="center")
        top.markdown(
            f'<div style="display:flex;align-items:center;gap:12px"><div class="erp-avatar-lg">{esc(initials(c["name"]))}</div>'
            f'<div><div class="erp-pname">{esc(c["name"])}</div><div class="erp-small">{esc(c["code"])} · '
            f'{esc(c["contact"] or "-")} · {esc(c["phone"] or "-")} · {esc(c["email"] or "-")}</div></div></div>',
            unsafe_allow_html=True)
        b = acts.columns(3)
        if b[0].button("✎ Düzenle", width="stretch", key="cust_edit"):
            customer_dialog(c)
        new_status = "Pasif" if c["status"] == "Aktif" else "Aktif"
        if b[1].button(f"→ {new_status}", width="stretch", key="cust_toggle"):
            db.set_customer_status(c["id"], new_status)
            flash(f"{c['name']} {new_status.lower()} yapıldı.")
            st.rerun()
        with b[2]:
            confirm_delete(f"cust_{c['id']}", c["name"], lambda: db.delete_customer(c["id"]) or bump("customers"))
        if c.get("address") or c.get("tax_no"):
            st.caption(f"Adres: {c['address'] or '-'} · Vergi No: {c['tax_no'] or '-'}")
        m = st.columns(3)
        m[0].metric("Toplam Satış", money(c["total_sales"]))
        m[1].metric("Açık Bakiye", money(c["balance"]))
        m[2].metric("Vadesi Geçen", money(c["overdue"]))
        sales = db.query("""SELECT s.*, p.name AS product FROM sales s LEFT JOIN products p ON p.id=s.product_id
                            WHERE s.customer_id=? ORDER BY s.date DESC""", (c["id"],))
        st.markdown("**Satış Geçmişi**")
        if sales:
            sdf = pd.DataFrame(sales)
            sdf["Tarih"] = sdf["date"].apply(dmy)
            sdf["Vade"] = sdf["due_date"].apply(dmy)
            sdf = sdf.rename(columns={"code": "Satış No", "product": "Ürün", "quantity": "Adet",
                                      "amount": "Tutar", "status": "Durum"})
            data_table(sdf, f"custsales{c['id']}", ["Satış No", "Tarih", "Ürün", "Adet", "Tutar", "Vade", "Durum"],
                       status_cols=("Durum",), money_cols=("Tutar",), selectable=False,
                       column_config={"Adet": st.column_config.NumberColumn(format="%g")},
                       title=f"{c['name']} - Satış Geçmişi")
        else:
            st.caption("Bu müşteriye ait satış yok.")
