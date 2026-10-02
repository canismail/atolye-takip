"""Malzeme Bileşenleri: ürünlerin alt bileşenlerinin (hammadde, sarf, yedek parça vb.)
tanımlandığı katalog sayfası. Miktar/stok takibi burada değil, Stok sayfasında yapılır —
burada sadece kalemin kendisi (kod, ad, kategori, birim, min. stok, birim maliyet, konum)
tanımlanır. Aynı 'stock_items' tablosunu Stok sayfasıyla ve ürünlerin Malzeme Bileşenleri
sekmesiyle paylaşır."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db, images
from core.ui import (bump, card_title, confirm_delete, data_table, flash, kpis, photo_input,
                     resolve_photo, search_filter)
from core.utils import money, num
from views.stock import add_stock_dialog


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
    min_qty = st.number_input("Minimum Stok", min_value=0.0, value=float(item.get("min_qty", 0)), step=1.0)

    # Hammadde ise ölçü / cins seçilir, parça ağırlığı ve maliyeti otomatik hesaplanır
    shape = a = b = length = density = None
    grade = ""
    weight = 0.0
    if cat == "Hammadde":
        st.markdown("**Ölçü ve ağırlık**")
        shapes = {"rect": "Dikdörtgen / Kare (en × boy)", "round": "Yuvarlak (çap)"}
        shapes["pipe"] = "Boru (dış çap × et kalınlığı)"
        keys = list(shapes)
        shape = st.radio("Kesit", keys, format_func=shapes.get, horizontal=True,
                         index=keys.index(item["shape"]) if item.get("shape") in keys else 0)
        if shape == "rect":
            d1, d2, d3 = st.columns(3)
            a = d1.number_input("En (mm)", min_value=0.0, value=float(item.get("dim_a") or 0), step=1.0)
            b = d2.number_input("Boy (mm)", min_value=0.0, value=float(item.get("dim_b") or 0), step=1.0)
            length = d3.number_input("Uzunluk (mm)", min_value=0.0, value=float(item.get("length_mm") or 0), step=1.0)
        elif shape == "pipe":
            d1, d2, d3 = st.columns(3)
            a = d1.number_input("Dış Çap (mm)", min_value=0.0, value=float(item.get("dim_a") or 0), step=1.0)
            b = d2.number_input("Et Kalınlığı (mm)", min_value=0.0, value=float(item.get("dim_b") or 0), step=0.1)
            length = d3.number_input("Uzunluk (mm)", min_value=0.0, value=float(item.get("length_mm") or 0), step=1.0)
            if a > 0 and b > 0 and 2 * b > a:
                st.error("Et kalınlığı dış çapın yarısından büyük olamaz.")
            elif a > 0 and b > 0:
                st.caption(f"İç çap: {num(a - 2 * b)} mm")
        else:
            d1, d3 = st.columns(2)
            a = d1.number_input("Çap (mm)", min_value=0.0, value=float(item.get("dim_a") or 0), step=1.0)
            b = 0.0
            length = d3.number_input("Uzunluk (mm)", min_value=0.0, value=float(item.get("length_mm") or 0), step=1.0)

        types = {t["name"]: t["density"] for t in db.get_material_types()}
        if item.get("grade") and item["grade"] not in types:  # ayarlardan silinmiş eski cins
            types[item["grade"]] = float(item.get("density") or db.DEFAULT_DENSITY)
        if types:
            names = list(types)
            grade = st.selectbox("Malzeme Cinsi", names,
                                 index=names.index(item["grade"]) if item.get("grade") in names else 0,
                                 format_func=lambda n: f"{n}  ({num(types[n])} g/cm³)")
            density = types[grade]
        else:
            st.warning("Malzeme cinsi tanımlı değil. **Ayarlar → Malzeme Cinsleri** bölümünden ekleyin.")
            density = 0.0
        weight = db.calc_unit_weight(shape, a, b, length, density)
        if weight > 0:
            vol = db.calc_volume_cm3(shape, a, b, length)
            st.success(f"Birim ağırlık: **{num(weight)} kg** / parça  ·  hacim {num(vol)} cm³ × {num(density)} g/cm³")
        else:
            st.caption("Ölçüleri ve cinsi seçince parça başına kilo otomatik hesaplanır.")
        kg_price = st.number_input("Kg Fiyatı", min_value=0.0, step=1.0,
                                   value=float(item["kg_price"] if item.get("kg_price") is not None
                                               else item.get("unit_cost", 0)))
        cost = db.hammadde_unit_cost(unit, weight, kg_price)
        if weight > 0:
            st.success(f"Birim maliyet: **{money(cost)}**  ({num(weight)} kg × {money(kg_price)}/kg)")
            if unit != "adet":
                st.caption("Ölçülü hammadde parça sayısıyla takip edilir; kaydedince birim **adet** yapılır.")
        else:
            st.caption("Ölçü girilmediği için birim maliyet ağırlıktan hesaplanamadı; kg fiyatı birim maliyet olarak kullanılır.")
    else:
        kg_price = None
        cost = st.number_input("Birim Maliyet", min_value=0.0, value=float(item.get("unit_cost", 0)), step=1.0)
    up, rm_img = photo_input(item.get("image"), f"mat_{item.get('id', 'new')}")
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
        if cat == "Hammadde" and shape == "pipe" and a > 0 and (b <= 0 or 2 * b > a):
            st.error("Boru için et kalınlığı 0'dan büyük ve dış çapın yarısından küçük/eşit olmalıdır.")
            return
        # Hammadde dışında ölçü alanları temizlenir
        try:
            img, old_img = resolve_photo(item.get("image"), up, rm_img, "malzeme")
        except ValueError as exc:
            st.error(str(exc))
            return
        if cat == "Hammadde" and weight > 0:
            unit = "adet"
        ham = cat == "Hammadde"
        vals = {"name": name.strip(), "category": cat, "unit": unit, "min_qty": min_qty, "unit_cost": cost,
                "shape": shape if ham else None, "dim_a": a if ham else None, "dim_b": b if ham else None,
                "length_mm": length if ham else None, "grade": (grade or None) if ham else None,
                "density": density if ham else None, "unit_weight": weight if ham else 0.0,
                "kg_price": kg_price if ham else None, "image": img}
        if item:
            db.save_material(vals, item["id"])
            images.delete_image(old_img)
            flash(f"{name} güncellendi.")
        else:
            sid = db.save_material(vals)
            st.session_state.selected_material = sid
            flash(f"{name} eklendi.")
        bump("materials")
        st.rerun()


def render(q: str = "") -> None:
    items = db.stock_items()
    kpis([
        {"icon": "▦", "color": "blue", "label": "Malzeme Bileşeni", "value": num(len(items))},
        {"icon": "□", "color": "green", "label": "Stokta Takip Edilen",
         "value": num(sum(1 for i in items if i["in_stock"]))},
        {"icon": "-", "color": "yellow", "label": "Stoğa Eklenmemiş",
         "value": num(sum(1 for i in items if not i["in_stock"]))},
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
            df["grade"] = df["grade"].fillna("")
            df["in_stock"] = df["in_stock"].apply(lambda v: "Stokta" if v else "-")
            df["unit_weight"] = df["unit_weight"].apply(lambda w: f"{num(w)} kg" if (w or 0) > 0 else "")
            df["kg_price"] = df["kg_price"].apply(lambda v: f"{money(v)}/kg" if pd.notna(v) and v else "")
            df = df.rename(columns={"code": "Kod", "name": "Bileşen", "category": "Kategori",
                                    "unit": "Birim", "min_qty": "Min. Stok", "unit_cost": "Birim Maliyet",
                                    "size": "Ölçü", "grade": "Cins",
                                    "unit_weight": "Birim Ağırlık", "kg_price": "Kg Fiyatı", "in_stock": "Stok"})
            df = search_filter(df, local, q)
            df = df.assign(Foto=df["image"].apply(images.thumb_uri))
        sel = data_table(
            df, "materials",
            ["Foto", "Kod", "Bileşen", "Kategori", "Ölçü", "Cins", "Birim Ağırlık", "Birim", "Min. Stok",
             "Kg Fiyatı", "Birim Maliyet", "Stok"],
            money_cols=("Birim Maliyet",),
            column_config={"Min. Stok": st.column_config.NumberColumn(format="%.2f"),
                           "Foto": st.column_config.ImageColumn("Foto", width="small")},
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
        mpath = images.image_path(item.get("image"))
        if mpath:
            st.image(str(mpath), width=150)
        top, acts = st.columns([1.6, 2.2], vertical_alignment="center")
        spec = ""
        if item["category"] == "Hammadde" and item.get("size"):
            spec = (f" · {item['size']}" + (f" · {item['grade']}" if item.get("grade") else "")
                    + (f" · {num(item['unit_weight'])} kg/parça" if item["unit_weight"] > 0 else ""))
        top.markdown(f"**{item['code']} · {item['name']}**  \n"
                     f"<span class='erp-small'>{item['category']}{spec} · {item['unit']} · "
                     f"Min. {num(item['min_qty'])}</span>",
                     unsafe_allow_html=True)
        b = acts.columns(3)
        if b[0].button("✎ Düzenle", width="stretch", key="mat_edit"):
            material_item_dialog(item)
        if not item["in_stock"]:
            if b[1].button("＋ Stoğa Ekle", type="primary", width="stretch", key="mat_to_stock"):
                add_stock_dialog(item)
        elif b[1].button("− Stoktan Kaldır", width="stretch", key="mat_from_stock"):
            err = db.remove_from_stock(item["id"])
            if err:
                st.error(err)
            else:
                flash(f"{item['name']} stok listesinden kaldırıldı.")
                bump("materials")
                st.rerun()
        with b[2]:
            confirm_delete(f"mat_{item['id']}", item["name"],
                           lambda: db.delete_stock_item(item["id"]) or bump("materials"))
        if item["in_stock"]:
            tot = (f" (toplam **{num(item['quantity'] * item['unit_weight'])} kg**)"
                   if item["unit_weight"] > 0 and item["unit"] == "adet" else "")
            st.caption(f"Mevcut stok: **{num(item['quantity'])} {item['unit']}**{tot} · "
                       f"Stok değeri: **{money(item['value'])}** — miktar Stok sayfasından güncellenir.")
        else:
            st.caption("Bu bileşen henüz stok listesinde değil. **＋ Stoğa Ekle** ile Stok sayfasına ekleyebilirsin.")
        used = db.query("""SELECT p.name, m.quantity FROM product_materials m
                           JOIN products p ON p.id=m.product_id WHERE m.stock_id=?""", (item["id"],))
        if used:
            st.caption("Kullanıldığı ürünler: " + ", ".join(
                f"{u['name']} ({num(u['quantity'])} {item['unit']})" for u in used))
