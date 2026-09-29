"""Malzeme Bileşenleri: ürünlerin alt bileşenlerinin (hammadde, sarf, yedek parça vb.)
tanımlandığı katalog sayfası. Miktar/stok takibi burada değil, Stok sayfasında yapılır —
burada sadece kalemin kendisi (kod, ad, kategori, birim, min. stok, birim maliyet, konum)
tanımlanır. Aynı 'stock_items' tablosunu Stok sayfasıyla ve ürünlerin Malzeme Bileşenleri
sekmesiyle paylaşır."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db
from core.ui import bump, card_title, confirm_delete, data_table, flash, kpis, search_filter
from core.utils import money, num


@st.dialog("Malzeme Bileşeni")
def material_item_dialog(item: dict | None = None) -> None:
    item = item or {}
    name = st.text_input("Bileşen Adı *", value=item.get("name", ""), placeholder="Örn. Alüminyum Profil")
    if item:
        st.caption(f"Kod: **{item['code']}**")
    elif name.strip():
        st.caption(f"Kod: **{db.code_from_name('stock_items', name)}**  _(isme göre otomatik oluşturulur)_")
    else:
        st.caption("Kod: bileşen adını yazınca otomatik oluşturulur.")
    c1, c2 = st.columns(2)
    cats = db.STOCK_CATEGORIES
    cat = c1.selectbox("Kategori", cats, index=cats.index(item["category"]) if item.get("category") in cats else 0)
    units = db.UNITS
    unit = c2.selectbox("Birim", units, index=units.index(item["unit"]) if item.get("unit") in units else 0)
    c3, c4 = st.columns(2)
    min_qty = c3.number_input("Minimum Stok", min_value=0.0, value=float(item.get("min_qty", 0)), step=1.0)
    cost = c4.number_input("Birim Maliyet", min_value=0.0, value=float(item.get("unit_cost", 0)), step=1.0)
    loc = st.text_input("Konum", value=item.get("location") or "", placeholder="A-01")
    if not item:
        st.caption("💡 Stok miktarını girmek için kaydettikten sonra **Stok** sayfasından "
                   "'± Stok Hareketi' ile giriş yapabilirsin.")

    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        if not name.strip():
            st.error("Bileşen adı zorunludur.")
            return
        if item:
            db.execute("UPDATE stock_items SET name=?, category=?, unit=?, min_qty=?, unit_cost=?, location=? "
                       "WHERE id=?", (name.strip(), cat, unit, min_qty, cost, loc.strip(), item["id"]))
            flash(f"{name} güncellendi.")
        else:
            code = db.code_from_name("stock_items", name)
            sid = db.execute("INSERT INTO stock_items(code, name, category, unit, quantity, min_qty, unit_cost, "
                             "location) VALUES (?,?,?,?,0,?,?,?)", (code, name.strip(), cat, unit, min_qty, cost, loc.strip()))
            st.session_state.selected_material = sid
            flash(f"{name} eklendi.")
        bump("materials")
        st.rerun()


def render(q: str = "") -> None:
    items = db.stock_items()
    kpis([
        {"icon": "▦", "color": "blue", "label": "Malzeme Bileşeni", "value": num(len(items))},
        {"icon": "!", "color": "red", "label": "Kritik Stok",
         "value": num(sum(1 for i in items if i["status"] == "Kritik"))},
        {"icon": "!", "color": "yellow", "label": "Minimuma Yakın",
         "value": num(sum(1 for i in items if i["status"] == "Minimuma Yakın"))},
    ], cols=3)

    with st.container(key="card_materials_list"):
        h = st.columns([2.4, 2, 1.5, 1.3], vertical_alignment="center")
        with h[0]:
            card_title("Malzeme Bileşenleri")
        local = h[1].text_input("Bileşen ara", placeholder="Bileşen ara...", label_visibility="collapsed",
                                key="mat_q")
        cat = h[2].selectbox("Kategori", ["Tüm Kategoriler"] + db.STOCK_CATEGORIES,
                             label_visibility="collapsed", key="mat_cat")
        if h[3].button("＋ Yeni Bileşen", type="primary", width="stretch"):
            material_item_dialog()

        df = pd.DataFrame(items)
        if not df.empty:
            if cat != "Tüm Kategoriler":
                df = df[df["category"] == cat]
            df = df.rename(columns={"code": "Kod", "name": "Bileşen", "category": "Kategori",
                                    "unit": "Birim", "min_qty": "Min. Stok", "unit_cost": "Birim Maliyet",
                                    "location": "Konum"})
            df = search_filter(df, local, q)
        sel = data_table(
            df, "materials",
            ["Kod", "Bileşen", "Kategori", "Birim", "Min. Stok", "Birim Maliyet", "Konum"],
            money_cols=("Birim Maliyet",),
            column_config={"Min. Stok": st.column_config.NumberColumn(format="%.2f")},
            title="Malzeme Bileşenleri",
        )
        if not items:
            st.caption("İlk bileşeni eklemek için **＋ Yeni Bileşen** butonunu kullanın.")
        elif sel is None:
            st.caption("Düzenlemek veya silmek için tablodan bir bileşen seçin.")

    if sel is not None:
        st.session_state.selected_material = sel
    msel = st.session_state.get("selected_material")
    item = next((i for i in items if i["id"] == msel), None) if msel else None
    if not item:
        return
    with st.container(key="card_material_detail"):
        top, acts = st.columns([2, 1.6], vertical_alignment="center")
        top.markdown(f"**{item['code']} · {item['name']}**  \n"
                     f"<span class='erp-small'>{item['category']} · {item['unit']} · Min. {num(item['min_qty'])} · "
                     f"Konum: {item['location'] or '-'}</span>", unsafe_allow_html=True)
        b = acts.columns(2)
        if b[0].button("✎ Düzenle", width="stretch", key="mat_edit"):
            material_item_dialog(item)
        with b[1]:
            confirm_delete(f"mat_{item['id']}", item["name"],
                           lambda: db.delete_stock_item(item["id"]) or bump("materials"))
        st.caption(f"Mevcut stok: **{num(item['quantity'])} {item['unit']}** · "
                   f"Stok değeri: **{money(item['value'])}** — miktar Stok sayfasından güncellenir.")
        used = db.query("""SELECT p.name, m.quantity FROM product_materials m
                           JOIN products p ON p.id=m.product_id WHERE m.stock_id=?""", (item["id"],))
        if used:
            st.caption("Kullanıldığı ürünler: " + ", ".join(
                f"{u['name']} ({num(u['quantity'])} {item['unit']})" for u in used))
