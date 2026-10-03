"""Stok: malzeme bileşenlerinin (Malzeme Bileşenleri sayfasında tanımlanır) mevcut
miktarlarını gösterir ve stok hareketi (giriş / çıkış / sayım) girilir. Yeni bileşen
tanımlamak veya kod/kategori/birim gibi detayları düzenlemek için Malzeme Bileşenleri
sayfası kullanılır."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db, images, metrics
from core.ui import bump, card_title, data_table, flash, go, kpis, search_filter
from core.utils import dmy, money, num


@st.dialog("Stok Hareketi")
def movement_dialog(item: dict) -> None:
    st.markdown(f"**{item['code']} · {item['name']}** — mevcut: {num(item['quantity'])} {item['unit']}")
    kind = st.radio("Hareket", ["Giriş (+)", "Çıkış (−)", "Sayım düzeltme (=)"], horizontal=True)
    if kind.startswith("Sayım"):
        target = st.number_input("Sayılan miktar", min_value=0.0, value=float(item["quantity"]), step=1.0)
        change = target - float(item["quantity"])
    else:
        amt = st.number_input(f"Miktar ({item['unit']})", min_value=0.0, value=0.0, step=1.0)
        change = amt if kind.startswith("Giriş") else -amt
    on = st.date_input("Tarih", format="DD.MM.YYYY")
    note = st.text_input("Açıklama", placeholder="Örn. Tedarikçi teslimatı, üretime çıkış...")
    new_qty = float(item["quantity"]) + change
    st.caption(f"Yeni miktar: **{num(new_qty)} {item['unit']}**")
    if new_qty < 0:
        st.warning("Çıkış miktarı mevcut stoktan fazla.")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch", disabled=change == 0 or new_qty < 0):
        db.add_stock_movement(item["id"], change, note or kind.split(" ")[0], on.isoformat())
        flash(f"{item['name']}: {'+' if change > 0 else ''}{num(change)} {item['unit']}")
        bump("stock")
        st.rerun()


@st.dialog("Stoğa Ekle")
def add_stock_dialog(item: dict | None = None, product: dict | None = None) -> None:
    """Malzeme bileşenini veya ürünü Stok sayfasına ekler (istenirse başlangıç miktarı girilir)."""
    target = None  # ("item", satır) | ("product", ürün)
    if item is not None:
        st.markdown(f"**{item['code']} · {item['name']}**")
        target = ("item", item)
    elif product is not None:
        st.markdown(f"**{product['code']} · {product['name']}** (ürün)")
        target = ("product", product)
    else:
        kind = st.radio("Ne eklenecek?", ["Malzeme Bileşeni", "Ürün"], horizontal=True)
        if kind == "Ürün":
            in_stock_pids = {i["product_id"] for i in db.stock_items(in_stock=True, with_products=True)
                             if i.get("product_id")}
            avail = [p for p in db.products_with_stats() if p["id"] not in in_stock_pids]
            empty_msg = "Stoğa eklenecek ürün yok. Önce **Ürünler** sayfasından ürün ekleyin."
            fmt = lambda p: f"{p['code']} · {p['name']}"  # noqa: E731
            kind_key = "product"
        else:
            avail = [i for i in db.stock_items() if not i["in_stock"]]
            empty_msg = ("Stoğa eklenecek bileşen yok. Önce **Malzeme Bileşenleri** sayfasından bileşen "
                         "tanımlayın (tanımlı bileşenlerin hepsi zaten stokta).")
            fmt = lambda i: f"{i['code']} · {i['name']}"  # noqa: E731
            kind_key = "item"
        if not avail:
            st.info(empty_msg)
            if st.button("Kapat", width="stretch"):
                st.rerun()
            return
        target = (kind_key, st.selectbox("Seçim", avail, format_func=fmt))
    kind_key, obj = target
    unit = "adet" if kind_key == "product" else obj["unit"]
    qty = st.number_input(f"Başlangıç miktarı ({unit})", min_value=0.0, value=0.0, step=1.0,
                          help="Boş (0) bırakırsan sadece stok listesine eklenir; miktarı sonra girebilirsin.")
    on = st.date_input("Tarih", format="DD.MM.YYYY")
    note = st.text_input("Açıklama", placeholder="Örn. Tedarikçi teslimatı / üretimden giriş")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Stoğa Ekle", type="primary", width="stretch"):
        if kind_key == "product":
            sid = db.add_product_to_stock(obj["id"], qty, note, on.isoformat())
        else:
            sid = obj["id"]
            db.add_to_stock(sid, qty, note, on.isoformat())
        st.session_state.selected_stock = sid
        flash(f"{obj['name']} stoğa eklendi.")
        bump("stock")
        st.rerun()


def render(q: str = "") -> None:
    items = db.stock_items(in_stock=True, with_products=True)
    kpis([
        {"icon": "□", "color": "blue", "label": "Stok Kalemi", "value": num(len(items))},
        {"icon": "₺", "color": "green", "label": "Stok Değeri", "value": money(metrics.stock_value())},
        {"icon": "!", "color": "red", "label": "Kritik Stok",
         "value": num(sum(1 for i in items if i["status"] == "Kritik"))},
        {"icon": "!", "color": "yellow", "label": "Minimuma Yakın",
         "value": num(sum(1 for i in items if i["status"] == "Minimuma Yakın"))},
    ])

    with st.container(key="card_stock_list"):
        h = st.columns([2.2, 2, 1.4, 1.4, 1.3], vertical_alignment="center")
        with h[0]:
            card_title("Stok Listesi")
        local = h[1].text_input("Stok ara", placeholder="Stok ara...", label_visibility="collapsed", key="stock_q")
        cat = h[2].selectbox("Kategori", ["Tüm Kategoriler"] + db.STOCK_CATEGORIES + ["Ürün"],
                             label_visibility="collapsed", key="stock_cat")
        stf = h[3].selectbox("Durum", ["Tüm Durumlar", "Normal", "Minimuma Yakın", "Kritik"],
                             label_visibility="collapsed", key="stock_st")
        if h[4].button("＋ Stoğa Ekle", type="primary", width="stretch"):
            add_stock_dialog()

        df = pd.DataFrame(items)
        if not df.empty:
            if cat != "Tüm Kategoriler":
                df = df[df["category"] == cat]
            if stf != "Tüm Durumlar":
                df = df[df["status"] == stf]
            df = df.rename(columns={"code": "Kod", "name": "Ürün / Malzeme", "category": "Kategori",
                                    "unit": "Birim", "quantity": "Mevcut", "min_qty": "Min.",
                                    "status": "Durum", "unit_cost": "Birim Maliyet", "sale_price": "Satış Fiyatı",
                                    "value": "Stok Değeri", "size": "Ölçü"})
            df = search_filter(df, local, q)
            df = df.assign(Foto=df["photo"].apply(images.thumb_uri))
        sel = data_table(
            df, "stock",
            ["Foto", "Kod", "Ürün / Malzeme", "Kategori", "Ölçü", "Birim", "Mevcut", "Min.", "Durum",
             "Birim Maliyet", "Satış Fiyatı", "Stok Değeri"],
            status_cols=("Durum",), money_cols=("Birim Maliyet", "Satış Fiyatı", "Stok Değeri"),
            column_config={"Foto": st.column_config.ImageColumn("Foto", width="small"),
                           "Mevcut": st.column_config.NumberColumn(format="%.2f"),
                           "Min.": st.column_config.NumberColumn(format="%.2f")},
            title="Stok Listesi",
        )
        if not items:
            st.caption("Stok listesi boş. **＋ Stoğa Ekle** ile bir malzeme bileşeni veya ürün ekleyin.")
        elif sel is None:
            st.caption("Stok hareketi girmek için tablodan bir satır seçin.")

    if sel is not None:
        st.session_state.selected_stock = sel
    ssel = st.session_state.get("selected_stock")
    item = next((i for i in items if i["id"] == ssel), None) if ssel else None

    if item:
        with st.container(key="card_stock_detail"):
            spath = images.image_path(item.get("photo"))
            if spath:
                st.image(str(spath), width=150)
            card_title(f"{item['code']} · {item['name']}")
            if item.get("size") or item.get("grade"):
                tot = (f" · toplam **{num(item['quantity'] * item['unit_weight'])} kg**"
                       if item["unit_weight"] > 0 and item["unit"] == "adet" else "")
                st.caption(f"{item['size']}" + (f" · {item['grade']}" if item.get("grade") else "")
                           + (f" · {num(item['unit_weight'])} kg/parça" if item["unit_weight"] > 0 else "") + tot)
            b = st.columns([1.5, 1.8, 2.7])
            if b[0].button("± Stok Hareketi", type="primary", width="stretch"):
                movement_dialog(item)
            if item.get("product_id"):
                if b[1].button("✎ Ürünü Aç", width="stretch"):
                    st.session_state.selected_product = item["product_id"]
                    go("products")
                    st.rerun()
            elif b[1].button("✎ Malzeme Bilgisini Düzenle", width="stretch"):
                st.session_state.selected_material = item["id"]
                go("materials")
                st.rerun()
            used = db.query("""SELECT p.code, p.name, m.quantity FROM product_materials m
                               JOIN products p ON p.id=m.product_id WHERE m.stock_id=?""", (item["id"],))
            if used:
                st.caption("Kullanıldığı ürünler: " + ", ".join(
                    f"{u['name']} ({num(u['quantity'])} {item['unit']})" for u in used))
            mv = db.query("SELECT * FROM stock_movements WHERE stock_id=? ORDER BY date DESC, id DESC LIMIT 50",
                          (item["id"],))
            st.markdown("**Hareket Geçmişi**")
            if mv:
                mdf = pd.DataFrame(mv)
                mdf["Tarih"] = mdf["date"].apply(dmy)
                mdf["Değişim"] = mdf["change"].apply(lambda v: f"{'+' if v > 0 else ''}{num(v)} {item['unit']}")
                mdf["Açıklama"] = mdf["note"].fillna("")
                data_table(mdf, f"stockmv{item['id']}", ["Tarih", "Değişim", "Açıklama"],
                          selectable=False, title=f"{item['name']} - Hareket Geçmişi")
            else:
                st.caption("Henüz hareket yok.")
