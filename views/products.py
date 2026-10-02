from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db, images
from core.ui import (badge, bump, card_title, confirm_delete, data_table, empty, esc, flash,
                     info_rows, photo_input, resolve_photo, search_filter)
from core.utils import dmy, money, num
from views.orders import order_dialog
from views.stock import add_stock_dialog

ICONS = ["📦", "🪑", "🚪", "🗄️", "⚙️", "🔩", "🔧", "🛠️", "🧰", "🪜", "🛞", "🔗"]


@st.dialog("Ürün")
def product_dialog(p: dict | None = None) -> None:
    p = p or {}
    name = st.text_input("Ürün Adı *", value=p.get("name", ""), placeholder="Örn. Çalışma Masası")
    if p:
        st.caption(f"Kod: **{p['code']}**")
    elif name.strip():
        st.caption(f"Kod: **{db.code_from_name('products', name)}**  _(isme göre otomatik oluşturulur)_")
    else:
        st.caption("Kod: ürün adını yazınca otomatik oluşturulur.")
    cats = db.PRODUCT_CATEGORIES
    existing = [r["category"] for r in db.query("SELECT DISTINCT category FROM products")]
    cats = cats + [c for c in existing if c not in cats]
    cat = st.selectbox("Kategori", cats, index=cats.index(p["category"]) if p.get("category") in cats else 0,
                       accept_new_options=True)
    c3, c4, c5 = st.columns([1.2, 1, 1])
    price = c3.number_input("Satış Fiyatı", min_value=0.0, value=float(p.get("unit_price", 0)), step=10.0)
    icon = c4.selectbox("Simge", ICONS, index=ICONS.index(p["icon"]) if p.get("icon") in ICONS else 0)
    status = c5.selectbox("Durum", ["Aktif", "Pasif"], index=1 if p.get("status") == "Pasif" else 0)
    desc = st.text_area("Açıklama", value=p.get("description") or "", height=80)
    up, rm_img = photo_input(p.get("image"), f"prod_{p.get('id', 'new')}")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        if not name.strip():
            st.error("Ürün adı zorunludur.")
            return
        try:
            img, old_img = resolve_photo(p.get("image"), up, rm_img, "urun")
        except ValueError as exc:
            st.error(str(exc))
            return
        vals = {"name": name.strip(), "category": cat or "Diğer", "icon": icon, "unit_price": price,
                "status": status, "description": desc.strip(), "image": img}
        if p:
            db.save_product(vals, p["id"])
            images.delete_image(old_img)
            flash(f"{name} güncellendi.")
        else:
            pid = db.save_product(vals)
            st.session_state.selected_product = pid
            flash(f"{name} eklendi.")
        bump("products")
        st.rerun()


@st.dialog("Malzeme Bileşeni")
def material_dialog(product: dict, row: dict | None = None) -> None:
    stocks = db.stock_items()
    if not stocks:
        st.warning("Önce **Malzeme Bileşenleri** sayfasından malzeme ekleyin; bileşenler oradan seçilir.")
        return
    labels = {s["id"]: f"{s['code']} · {s['name']} ({s['unit']})" for s in stocks}
    ids = list(labels)
    default = ids.index(row["stock_id"]) if row and row["stock_id"] in ids else 0
    sid = st.selectbox("Malzeme", ids, index=default, format_func=labels.get, disabled=bool(row))
    unit = next(s["unit"] for s in stocks if s["id"] == sid)
    qty = st.number_input(f"Adet / Miktar ({unit})", min_value=0.0,
                          value=float(row["quantity"]) if row else 1.0, step=1.0)
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch", disabled=qty <= 0):
        db.save_product_material(product["id"], sid, qty, row["id"] if row else None)
        flash("Bileşen kaydedildi.")
        bump("bom")
        st.rerun()


@st.dialog("Operasyon")
def operation_dialog(product: dict, row: dict | None = None) -> None:
    name = st.text_input("Operasyon Adı *", value=row["name"] if row else "", placeholder="Örn. Kaynak")
    mins = st.number_input("Süre (dakika)", min_value=0.0, value=float(row["minutes"]) if row else 10.0, step=5.0)
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        if not name.strip():
            st.error("Operasyon adı zorunludur.")
            return
        db.save_operation(product["id"], name, mins, row["id"] if row else None)
        flash("Operasyon kaydedildi.")
        bump("ops")
        st.rerun()


def _row_actions(prefix: str, table: str, product: dict, row: dict, label: str, edit_fn) -> None:
    b = st.columns(4)
    if b[0].button("✎ Düzenle", key=f"{prefix}_edit", width="stretch"):
        edit_fn(product, row)
    if b[1].button("▲ Yukarı", key=f"{prefix}_up", width="stretch"):
        db.move_row(table, product["id"], row["id"], -1)
        st.rerun()
    if b[2].button("▼ Aşağı", key=f"{prefix}_down", width="stretch"):
        db.move_row(table, product["id"], row["id"], +1)
        st.rerun()
    with b[3]:
        def _del():
            db.delete_row(table, product["id"], row["id"])
            bump(prefix)
        confirm_delete(f"{prefix}_{row['id']}", label, _del)


def render(q: str = "") -> None:
    products = db.products_with_stats()

    with st.container(key="card_prod_list"):
        h = st.columns([2.4, 2, 1.5, 1.3], vertical_alignment="center")
        with h[0]:
            card_title("Ürün Listesi")
        local = h[1].text_input("Ürün ara", placeholder="Ürün ara...", label_visibility="collapsed", key="prod_q")
        stf = h[2].selectbox("Durum", ["Tüm Durumlar", "Aktif", "Pasif"], label_visibility="collapsed", key="prod_st")
        if h[3].button("＋ Yeni Ürün", type="primary", width="stretch"):
            product_dialog()
        df = pd.DataFrame(products)
        if not df.empty:
            if stf != "Tüm Durumlar":
                df = df[df["status"] == stf]
            df["Toplam Süre"] = df["total_minutes"].apply(lambda m: f"{num(m)} dk")
            df = df.rename(columns={"code": "Kod", "name": "Ürün", "category": "Kategori",
                                    "material_count": "Malzeme", "operation_count": "Operasyon",
                                    "unit_price": "Satış Fiyatı", "material_cost": "Malzeme Maliyeti",
                                    "status": "Durum"})
            df = search_filter(df, local, q)
            df = df.assign(Foto=df["image"].apply(images.thumb_uri))
        sel = data_table(df, "products",
                         ["Foto", "Kod", "Ürün", "Kategori", "Malzeme", "Operasyon", "Toplam Süre",
                          "Malzeme Maliyeti", "Satış Fiyatı", "Durum"],
                         status_cols=("Durum",), money_cols=("Satış Fiyatı", "Malzeme Maliyeti"),
                         column_config={"Foto": st.column_config.ImageColumn("Foto", width="small")},
                         title="Ürün Listesi")
        if not products:
            st.caption("İlk ürünü eklemek için **＋ Yeni Ürün** butonunu kullanın.")

    if not products:
        return
    if sel is not None:
        st.session_state.selected_product = sel
    pid = st.session_state.get("selected_product")
    product = next((p for p in products if p["id"] == pid), products[0])

    left, right = st.columns([1, 3.2])
    with left.container(key="card_prod_summary"):
        ppath = images.image_path(product.get("image"))
        if ppath:
            st.image(str(ppath))
        st.markdown(
            (f'<div class="erp-product-image">{esc(product["icon"])}</div>' if not ppath else "")
            + f'<div class="erp-pname">{esc(product["name"])}</div>'
            f'<div class="erp-small">{esc(product["code"])}</div><br>{badge("● " + product["status"], "green" if product["status"] == "Aktif" else "gray")}'
            + info_rows([
                ("Kategori", esc(product["category"])),
                ("Toplam Süre", f"{num(product['total_minutes'])} dk"),
                ("Malzeme", f"{product['material_count']} adet"),
                ("Operasyon", f"{product['operation_count']} adet"),
                ("Malzeme Maliyeti", money(product["material_cost"])),
                ("Satış Fiyatı", money(product["unit_price"])),
            ]),
            unsafe_allow_html=True,
        )
        if product.get("description"):
            st.caption(product["description"])
        if st.button("✎ Düzenle", type="primary", width="stretch", key="prod_edit"):
            product_dialog(product)
        srow = db.one("SELECT id, quantity, in_stock FROM stock_items WHERE product_id=?", (product["id"],))
        if srow and srow["in_stock"]:
            st.caption(f"Stokta: **{num(srow['quantity'])} adet**")
            if st.button("− Stoktan Kaldır", width="stretch", key="prod_from_stock"):
                err = db.remove_from_stock(srow["id"])
                if err:
                    st.error(err)
                else:
                    flash(f"{product['name']} stok listesinden kaldırıldı.")
                    st.rerun()
        elif st.button("＋ Stoğa Ekle", width="stretch", key="prod_to_stock"):
            add_stock_dialog(product=product)
        confirm_delete(f"prod_{product['id']}", product["name"],
                       lambda: db.delete_product(product["id"]) or bump("products"))

    with right.container(key="card_prod_detail"):
        t1, t2, t3 = st.tabs(["Malzeme Bileşenleri", "Operasyonlar", "Siparişler"])
        with t1:
            h1, h2 = st.columns([3, 1], vertical_alignment="center")
            h1.markdown("**📦 Malzeme Bileşenleri**")
            if h2.button("＋ Bileşen Ekle", type="primary", width="stretch", key="bom_add"):
                material_dialog(product)
            mats = db.product_materials(product["id"])
            mdf = pd.DataFrame(mats)
            if not mdf.empty:
                mdf["Adet"] = mdf.apply(lambda r: f"{num(r['quantity'])} {r['unit']}", axis=1)
                mdf = mdf.rename(columns={"seq": "Sıra", "code": "Kod", "name": "Malzeme Adı",
                                          "unit_cost": "Birim Maliyet", "cost": "Maliyet"})
            msel = data_table(mdf, f"bom{product['id']}_{st.session_state.get('_nonce_bom', 0)}",
                              ["Sıra", "Kod", "Malzeme Adı", "Adet", "Birim Maliyet", "Maliyet"],
                              money_cols=("Birim Maliyet", "Maliyet"),
                              title=f"{product['name']} - Malzeme Bileşenleri")
            if msel is not None:
                row = next(m for m in mats if m["id"] == msel)
                _row_actions("bom", "product_materials", product, row, row["name"], material_dialog)
        with t2:
            h1, h2 = st.columns([3, 1], vertical_alignment="center")
            h1.markdown("**⚙ Operasyonlar**")
            if h2.button("＋ Operasyon Ekle", type="primary", width="stretch", key="op_add"):
                operation_dialog(product)
            ops = db.product_operations(product["id"])
            odf = pd.DataFrame(ops)
            if not odf.empty:
                odf["Süre"] = odf["minutes"].apply(lambda m: f"{num(m)} dk")
                odf = odf.rename(columns={"seq": "Sıra", "name": "Operasyon"})
            osel = data_table(odf, f"ops{product['id']}_{st.session_state.get('_nonce_ops', 0)}",
                              ["Sıra", "Operasyon", "Süre"],
                              title=f"{product['name']} - Operasyonlar")
            if ops:
                st.caption(f"Toplam süre: **{num(sum(o['minutes'] for o in ops))} dk**")
            if osel is not None:
                row = next(o for o in ops if o["id"] == osel)
                _row_actions("ops", "product_operations", product, row, row["name"], operation_dialog)
        with t3:
            h1, h2 = st.columns([3, 1], vertical_alignment="center")
            h1.markdown("**↗ Siparişler**")
            if h2.button("＋ Sipariş Oluştur", type="primary", width="stretch", key="prod_wo_add"):
                order_dialog(None, product["id"])
            wos = [w for w in db.work_orders_list() if w["product_id"] == product["id"]]
            if wos:
                wdf = pd.DataFrame(wos)
                wdf["Termin"] = wdf["due_date"].apply(dmy)
                wdf = wdf.rename(columns={"code": "Sipariş", "customer": "Müşteri", "quantity": "Adet",
                                          "progress": "İlerleme", "status": "Durum"})
                data_table(wdf, f"prodwo{product['id']}",
                           ["Sipariş", "Müşteri", "Adet", "Termin", "İlerleme", "Durum"],
                           status_cols=("Durum",), selectable=False,
                           column_config={"İlerleme": st.column_config.ProgressColumn(
                               min_value=0, max_value=100, format="%d%%")},
                           title=f"{product['name']} - Siparişler")
            else:
                empty("Bu ürüne ait sipariş yok.")
