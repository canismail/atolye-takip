from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

from core import db
from core.ui import bump, card_title, confirm_delete, data_table, flash, kpis, search_filter
from core.utils import dmy, num, to_date


@st.dialog("Sipariş")
def order_dialog(wo: dict | None = None, product_id: int | None = None) -> None:
    wo = wo or {}
    products = db.query("SELECT id, code, name, status FROM products ORDER BY name")
    if not products:
        st.warning("Önce **Ürünler** sayfasından ürün ekleyin.")
        return
    customers = db.query("SELECT id, name FROM customers ORDER BY name")
    pmap = {p["id"]: f"{p['name']} ({p['code']})" + (" · Pasif" if p["status"] == "Pasif" else "") for p in products}
    pids = list(pmap)
    pdefault = wo.get("product_id") or product_id
    pid = st.selectbox("Ürün *", pids, index=pids.index(pdefault) if pdefault in pids else 0, format_func=pmap.get)
    cmap = {None: "— Stok için üretim (müşterisiz) —"} | {c["id"]: c["name"] for c in customers}
    cids = list(cmap)
    cid = st.selectbox("Müşteri", cids, index=cids.index(wo.get("customer_id")) if wo.get("customer_id") in cids else 0,
                       format_func=cmap.get)
    c1, c2 = st.columns(2)
    qty = c1.number_input("Adet *", min_value=1.0, value=float(wo.get("quantity", 1)), step=1.0)
    due = c2.date_input("Termin", value=to_date(wo.get("due_date")) or date.today() + timedelta(days=7),
                        format="DD.MM.YYYY")
    c3, c4 = st.columns(2)
    status = c3.selectbox("Durum", db.ORDER_STATUSES,
                          index=db.ORDER_STATUSES.index(wo["status"]) if wo.get("status") in db.ORDER_STATUSES else 0)
    prog = c4.slider("İlerleme %", 0, 100, int(wo.get("progress", 0)), step=5,
                     disabled=status in ("Tamamlandı",))
    note = st.text_area("Not", value=wo.get("note") or "", height=70)

    mins = db.scalar("SELECT COALESCE(SUM(minutes),0) FROM product_operations WHERE product_id=?", (pid,))
    need = db.query("""SELECT s.name, s.unit, s.quantity AS have, m.quantity*? AS need
                       FROM product_materials m JOIN stock_items s ON s.id=m.stock_id WHERE m.product_id=?""",
                    (qty, pid))
    st.caption(f"Tahmini üretim süresi: **{num(mins * qty / 60, 1)} saat** ({num(mins)} dk × {num(qty)})")
    short = [n for n in need if n["need"] > n["have"]]
    if short:
        st.warning("Stok yetersiz: " + ", ".join(
            f"{n['name']} (gerekli {num(n['need'])} {n['unit']}, mevcut {num(n['have'])})" for n in short))

    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        if status == "Üretimde" and prog == 0:
            prog = 5
        data = {"customer_id": cid, "product_id": pid, "quantity": qty, "due_date": due.isoformat(),
                "progress": prog, "status": status, "note": note.strip(),
                "completed_at": wo.get("completed_at")}
        db.save_work_order(data, wo.get("id"))
        flash("İş emri kaydedildi.")
        bump("orders")
        st.rerun()


@st.dialog("İlerleme Güncelle")
def progress_dialog(wo: dict) -> None:
    st.markdown(f"**{wo['code']} · {wo['product']}** — {num(wo['quantity'])} adet")
    prog = st.slider("İlerleme %", 0, 100, int(wo["progress"]), step=5)
    new_status = db.status_for_progress(prog, wo["status"])
    st.caption(f"Yeni durum: **{new_status}**")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        db.update_progress(wo["id"], prog)
        flash(f"{wo['code']}: %{prog} · {new_status}")
        bump("orders")
        st.rerun()


def render(q: str = "") -> None:
    wos = db.work_orders_list()
    today = date.today().isoformat()
    open_ = [w for w in wos if w["status"] in ("Bekliyor", "Üretimde")]
    late = [w for w in open_ if w["due_date"] and w["due_date"] < today]
    kpis([
        {"icon": "↗", "color": "blue", "label": "Açık Sipariş", "value": num(len(open_))},
        {"icon": "⚙", "color": "yellow", "label": "Üretimde",
         "value": num(sum(1 for w in wos if w["status"] == "Üretimde"))},
        {"icon": "!", "color": "red", "label": "Termini Geçen", "value": num(len(late))},
        {"icon": "✓", "color": "green", "label": "Bu Ay Tamamlanan",
         "value": num(sum(1 for w in wos if w["status"] == "Tamamlandı" and (w["completed_at"] or "")[:7] == today[:7]))},
    ])

    with st.container(key="card_orders"):
        h = st.columns([2.4, 2, 1.5, 1.4], vertical_alignment="center")
        with h[0]:
            card_title("Siparişler")
        local = h[1].text_input("İş emri ara", placeholder="İş emri ara...", label_visibility="collapsed", key="wo_q")
        stf = h[2].selectbox("Durum", ["Açık Siparişler", "Tümü"] + db.ORDER_STATUSES,
                             label_visibility="collapsed", key="wo_st")
        if h[3].button("＋ Yeni Sipariş", type="primary", width="stretch"):
            order_dialog()

        df = pd.DataFrame(wos)
        if not df.empty:
            if stf == "Açık Siparişler":
                df = df[df["status"].isin(["Bekliyor", "Üretimde"])]
            elif stf != "Tümü":
                df = df[df["status"] == stf]
            df["Termin"] = df["due_date"].apply(dmy)
            df["Durum"] = df.apply(lambda r: "Gecikti" if r["status"] in ("Bekliyor", "Üretimde")
                                   and r["due_date"] and r["due_date"] < today else r["status"], axis=1)
            df["Süre (saat)"] = (df["unit_minutes"] * df["quantity"] / 60).apply(lambda h: f"{num(h, 1)} sa")
            df["customer"] = df["customer"].fillna("Stok üretimi")
            df = df.rename(columns={"code": "Sipariş", "customer": "Müşteri", "product": "Ürün",
                                    "quantity": "Adet", "progress": "İlerleme"})
            df = search_filter(df, local, q)
        sel = data_table(df, "orders",
                         ["Sipariş", "Müşteri", "Ürün", "Adet", "Termin", "Süre (saat)", "İlerleme", "Durum"],
                         status_cols=("Durum",), status_colors={"Bekliyor": "gray", "Üretimde": "yellow"},
                         column_config={
                             "Adet": st.column_config.NumberColumn(format="%g"),
                             "İlerleme": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d%%")},
                         title="Siparişler")
        if sel is None:
            st.caption("İşlem yapmak için tablodan bir sipariş seçin.")

    if sel is not None:
        wo = next((w for w in wos if w["id"] == sel), None)
        if wo:
            with st.container(key="card_order_actions"):
                card_title(f"{wo['code']} · {wo['product']}")
                b = st.columns([1.3, 1.2, 1, 1, 1.5])
                if b[0].button("⟳ İlerleme Güncelle", type="primary", width="stretch",
                               disabled=wo["status"] in ("Tamamlandı", "İptal")):
                    progress_dialog(wo)
                if b[1].button("✓ Tamamlandı", width="stretch", disabled=wo["status"] in ("Tamamlandı", "İptal")):
                    db.update_progress(wo["id"], 100)
                    flash(f"{wo['code']} tamamlandı.")
                    bump("orders")
                    st.rerun()
                if b[2].button("✎ Düzenle", width="stretch"):
                    order_dialog(wo)
                with b[3]:
                    def _del():
                        db.execute("DELETE FROM work_orders WHERE id=?", (wo["id"],))
                        bump("orders")
                    confirm_delete(f"wo_{wo['id']}", wo["code"], _del)
                if wo["status"] == "İptal":
                    if b[4].button("↺ Yeniden Aç", width="stretch"):
                        db.execute("UPDATE work_orders SET status=? WHERE id=?",
                                   (db.status_for_progress(wo["progress"], "Bekliyor"), wo["id"]))
                        bump("orders")
                        st.rerun()
                elif wo["status"] != "Tamamlandı":
                    if b[4].button("✕ İptal Et", width="stretch"):
                        db.execute("UPDATE work_orders SET status='İptal' WHERE id=?", (wo["id"],))
                        flash(f"{wo['code']} iptal edildi.", "✕")
                        bump("orders")
                        st.rerun()
                if wo.get("note"):
                    st.caption(f"Not: {wo['note']}")
                need = db.query("""SELECT s.name, s.unit, s.quantity AS have, m.quantity*? AS need
                                   FROM product_materials m JOIN stock_items s ON s.id=m.stock_id
                                   WHERE m.product_id=?""", (wo["quantity"], wo["product_id"]))
                if need:
                    st.markdown("**Malzeme İhtiyacı**")
                    ndf = pd.DataFrame(need)
                    ndf["Gerekli"] = ndf.apply(lambda r: f"{num(r['need'])} {r['unit']}", axis=1)
                    ndf["Mevcut"] = ndf.apply(lambda r: f"{num(r['have'])} {r['unit']}", axis=1)
                    ndf["Durum"] = ndf.apply(lambda r: "Normal" if r["have"] >= r["need"] else "Kritik", axis=1)
                    ndf = ndf.rename(columns={"name": "Malzeme"})
                    ndf["id"] = range(len(ndf))
                    data_table(ndf, f"woneed{wo['id']}", ["Malzeme", "Gerekli", "Mevcut", "Durum"],
                               status_cols=("Durum",), selectable=False,
                               status_colors={"Normal": "green", "Kritik": "red"},
                               title=f"{wo['code']} - Malzeme İhtiyacı")
