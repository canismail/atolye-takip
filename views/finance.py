from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import db, metrics
from core.ui import bump, card_title, confirm_delete, data_table, flash, kpis, nav_button, search_filter
from core.utils import dmy, month_label, money, num, pct, to_date


@st.dialog("Gelir / Gider")
def finance_dialog(t: dict | None = None) -> None:
    t = t or {}
    kind = st.radio("Tür", ["Gelir", "Gider"], index=1 if t.get("type") == "Gider" else 0, horizontal=True)
    cats = db.INCOME_CATEGORIES if kind == "Gelir" else db.EXPENSE_CATEGORIES
    used = [r["category"] for r in db.query("SELECT DISTINCT category FROM transactions WHERE type=?", (kind,))]
    cats = cats + [c for c in used if c not in cats]
    cat = st.selectbox("Kategori", cats, index=cats.index(t["category"]) if t.get("category") in cats else 0,
                       accept_new_options=True, key=f"fin_cat_{kind}")
    desc = st.text_input("Açıklama", value=t.get("description") or "", placeholder="Örn. Atölye kirası")
    c1, c2 = st.columns(2)
    doc = c1.text_input("Belge No", value=t.get("doc_no") or "", placeholder="F-0001")
    amount = c2.number_input("Tutar", min_value=0.0, value=float(t.get("amount", 0)), step=100.0)
    on = st.date_input("Tarih", value=to_date(t.get("date")) or date.today(), format="DD.MM.YYYY")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch", disabled=amount <= 0):
        vals = {"date": on.isoformat(), "type": kind, "category": cat or "Diğer", "description": desc.strip(),
                "doc_no": doc.strip(), "amount": amount}
        db.save_transaction(vals, t["id"] if t else None)
        flash(f"{kind} kaydedildi: {money(amount)}")
        bump("finance")
        st.rerun()


def render(q: str = "") -> None:
    months = metrics.months_with_data()
    kpi_box = st.container()

    with st.container(key="card_finance"):
        h = st.columns([2.2, 1.7, 1.3, 1.6, 1.4], vertical_alignment="center")
        with h[0]:
            card_title("Gelir / Gider Hareketleri")
        local = h[1].text_input("Hareket ara", placeholder="Hareket ara...", label_visibility="collapsed", key="fin_q")
        kind = h[2].selectbox("Tür", ["Tümü", "Gelir", "Gider"], label_visibility="collapsed", key="fin_kind")
        month = h[3].selectbox("Dönem", ["Tüm Dönemler"] + months,
                               index=1 + months.index(metrics.this_month()),
                               format_func=lambda m: m if m == "Tüm Dönemler" else month_label(m),
                               label_visibility="collapsed", key="fin_month")
        if h[4].button("＋ Yeni Hareket", type="primary", width="stretch"):
            finance_dialog()

        km = None if month == "Tüm Dönemler" else month
        rows = db.query("SELECT * FROM transactions ORDER BY date DESC, id DESC")
        df = pd.DataFrame(rows)
        if not df.empty:
            if km:
                df = df[df["date"].str[:7] == km]
            if kind != "Tümü":
                df = df[df["type"] == kind]
            df["Tarih"] = df["date"].apply(dmy)
            df["Tutar"] = df.apply(lambda r: r["amount"] if r["type"] == "Gelir" else -r["amount"], axis=1)
            df["Kaynak"] = df["sale_id"].apply(lambda v: "Otomatik (satış)" if pd.notna(v) else "Manuel")
            df = df.rename(columns={"type": "Tür", "category": "Kategori", "description": "Açıklama",
                                    "doc_no": "Belge No"})
            df = search_filter(df, local, q)
        sel = data_table(df, "finance", ["Tarih", "Tür", "Kategori", "Açıklama", "Belge No", "Kaynak", "Tutar"],
                         status_cols=("Tür",), colored_money=("Tutar",), title="Gelir / Gider Hareketleri")
        if not rows:
            st.caption("İlk hareketi eklemek için **＋ Yeni Hareket** butonunu kullanın. "
                       "Tahsil edilen satışlar buraya otomatik düşer.")
        elif sel is None:
            st.caption("Düzenlemek veya silmek için bir hareket seçin.")

    inc = metrics.tx_total("Gelir", km)
    exp = metrics.tx_total("Gider", km)
    net = inc - exp
    with kpi_box:
        kpis([
            {"icon": "↑", "color": "green", "label": "Toplam Gelir", "value": money(inc)},
            {"icon": "↓", "color": "red", "label": "Toplam Gider", "value": money(exp)},
            {"icon": "₺", "color": "purple", "label": "Net Sonuç", "value": money(net)},
            {"icon": "%", "color": "yellow", "label": "Kâr Marjı", "value": pct(net / inc * 100) if inc else "-"},
        ])

    if sel is None:
        return
    t = next((r for r in rows if r["id"] == sel), None)
    if not t:
        return
    with st.container(key="card_fin_actions"):
        card_title(f"{dmy(t['date'])} · {t['type']} · {t['category']} · {money(t['amount'])}")
        if t["sale_id"]:
            st.info("Bu kayıt tahsil edilen bir satıştan otomatik oluşturuldu. Değiştirmek için ilgili satışı "
                    "düzenleyin ya da tahsilatı geri alın.")
            nav_button("Satışlara Git", "sales", "fin_goto_sales")
            return
        b = st.columns([1, 1, 3])
        if b[0].button("✎ Düzenle", width="stretch", key="fin_edit"):
            finance_dialog(t)
        with b[1]:
            def _del():
                db.delete_transaction(t["id"])
                bump("finance")
            confirm_delete(f"fin_{t['id']}", f"{t['category']} {money(t['amount'])}", _del)
