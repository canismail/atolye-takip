"""Makineler: atölyedeki tezgâhların tanımı. Üretim Planı bu listeden (aktif olanlarla) çalışır."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import db
from core.ui import bump, card_title, confirm_delete, data_table, flash, kpis, search_filter
from core.utils import num

NEW_TYPE = "➕ Yeni tür..."


@st.dialog("Makine")
def machine_dialog(m: dict | None = None) -> None:
    m = m or {}
    name = st.text_input("Makine Adı *", value=m.get("name", ""), placeholder="Örn. Torna 3")
    types = db.machine_types()
    cur = m.get("type") or (types[0] if types else "")
    opts = types + [NEW_TYPE]
    sel = st.selectbox("Makine Türü *", opts, index=opts.index(cur) if cur in opts else 0,
                       help="Operasyonlar makine türüne göre atanır; aynı türdeki makineler birbirinin yedeğidir.")
    mtype = st.text_input("Yeni tür adı", placeholder="Örn. Taşlama") if sel == NEW_TYPE else sel
    c1, c2 = st.columns(2)
    hours = c1.number_input("Günlük çalışma (saat)", min_value=0.5, max_value=24.0,
                            value=float(m.get("daily_hours", 8)), step=0.5)
    active = c2.radio("Durum", ["Aktif", "Pasif"], index=0 if m.get("active", 1) else 1, horizontal=True)
    chg = st.number_input("Parça ayarlama süresi (dakika)", min_value=0.0, step=15.0,
                          value=float(m.get("changeover_minutes", 120)),
                          help="Bu makinede her operasyondan önce harcanan ayarlama / sök-tak süresi (varsayılan 2 saat). "
                               "Operasyonda ayrıca sök-tak süresi girilmişse o geçerli olur.")
    note = st.text_input("Not", value=m.get("note") or "", placeholder="İsteğe bağlı")
    f1, f2 = st.columns(2)
    if f1.button("Vazgeç", width="stretch"):
        st.rerun()
    if f2.button("Kaydet", type="primary", width="stretch"):
        if not name.strip() or not mtype.strip():
            st.error("Makine adı ve türü zorunludur.")
            return
        db.save_machine(name, mtype, hours, active == "Aktif", note, m.get("id"), chg)
        flash(f"{name.strip()} {'güncellendi' if m else 'eklendi'}.")
        bump("machines")
        st.rerun()


def render(q: str = "") -> None:
    rows = db.machines_list()
    active = [r for r in rows if r["active"]]
    kpis([
        {"icon": "⚙", "color": "blue", "label": "Toplam Makine", "value": num(len(rows))},
        {"icon": "✓", "color": "green", "label": "Aktif", "value": num(len(active))},
        {"icon": "⏸", "color": "yellow", "label": "Pasif",
         "value": num(len(rows) - len(active))},
        {"icon": "◷", "color": "purple", "label": "Günlük Makine Saati",
         "value": f"{num(sum(r['daily_hours'] for r in active))} saat"},
    ])
    with st.container(key="card_machines"):
        h = st.columns([2.4, 2, 1.4], vertical_alignment="center")
        with h[0]:
            card_title("Makine Listesi")
        local = h[1].text_input("Makine ara", placeholder="Makine ara...", label_visibility="collapsed", key="mach_q")
        if h[2].button("＋ Yeni Makine", type="primary", width="stretch"):
            machine_dialog()
        df = pd.DataFrame(rows)
        if not df.empty:
            df["Durum"] = df["active"].map({1: "Aktif", 0: "Pasif"})
            df["Günlük Saat"] = df["daily_hours"].apply(lambda v: f"{num(v)} saat")
            df["Ayarlama"] = df["changeover_minutes"].apply(lambda v: f"{num(v / 60)} saat" if v else "-")
            df = df.rename(columns={"name": "Makine", "type": "Tür", "note": "Not"})
            df["Not"] = df["Not"].fillna("")
            df = search_filter(df, local, q)
        sel = data_table(df, f"machines_{st.session_state.get('_nonce_machines', 0)}",
                         ["Makine", "Tür", "Günlük Saat", "Ayarlama", "Durum", "Not"],
                         status_cols=("Durum",), status_colors={"Aktif": "green", "Pasif": "gray"},
                         title="Makineler")
        if not rows:
            st.caption("İlk makineyi eklemek için **＋ Yeni Makine** butonunu kullanın.")
        elif sel is None:
            st.caption("Düzenlemek, aktif/pasif yapmak veya silmek için tablodan bir makine seçin. "
                       "Pasif makineler üretim planına girmez.")
    if sel is None:
        return
    m = next((r for r in rows if r["id"] == sel), None)
    if not m:
        return
    with st.container(key="card_machine_detail"):
        top, acts = st.columns([2, 1.6], vertical_alignment="center")
        top.markdown(f"**{m['name']}** · {m['type']} · {num(m['daily_hours'])} saat/gün · ayarlama {num(m['changeover_minutes'] / 60)} sa · "
                     f"{'Aktif' if m['active'] else 'Pasif'}")
        b = acts.columns(3)
        if b[0].button("✎ Düzenle", width="stretch", key="mach_edit"):
            machine_dialog(m)
        if b[1].button("→ Pasif" if m["active"] else "→ Aktif", width="stretch", key="mach_toggle"):
            db.set_machine_active(m["id"], not m["active"])
            flash(f"{m['name']} {'pasif' if m['active'] else 'aktif'} yapıldı.")
            bump("machines")
            st.rerun()
        with b[2]:
            confirm_delete(f"mach_{m['id']}", m["name"], lambda: db.delete_machine(m["id"]) or bump("machines"))
