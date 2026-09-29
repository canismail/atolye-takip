"""Üretim Planı: ürünlerin operasyon sürelerine (+ buffer) göre günlük/haftalık üretilebilecek
adet, belirli bir adet için gereken süre/bitiş tarihi ve açık siparişlerin sıralı iş takvimi."""
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from core import db, planning as pl
from core.ui import card_title, data_table, flash, kpis, search_filter
from core.utils import dmy, num

WEEKDAYS = {5: "Pazartesi - Cuma (5 gün)", 6: "Pazartesi - Cumartesi (6 gün)", 7: "Haftanın 7 günü"}


def _params(S: dict) -> dict:
    hours = float(S.get("plan_daily_hours") or 8)
    workers = max(1, int(float(S.get("plan_workers") or 1)))
    return {
        "hours": hours, "workers": workers,
        "week_days": int(float(S.get("plan_week_days") or 5)),
        "buffer": float(S.get("plan_buffer_pct") or 0),
        "cap": hours * 60 * workers,  # günlük kapasite (dk)
    }


def render(q: str = "") -> None:
    S = db.get_settings()
    P = _params(S)
    products = db.products_with_stats()
    orders = [w for w in db.work_orders_list() if w["status"] in ("Bekliyor", "Üretimde")]

    # ---- açık siparişlerin sıralı takvimi (KPI için önce hesaplanır)
    sched, day, used = [], date.today(), 0.0
    for w in sorted(orders, key=lambda w: (w["due_date"] or "9999", w["id"])):
        unit = pl.buffered(w["unit_minutes"], P["buffer"])
        rem = pl.remaining_units(w["quantity"], w["progress"])
        need = rem * unit
        if unit <= 0:
            sched.append({"w": w, "rem": rem, "need": 0.0, "start": None, "end": None, "state": "Operasyon yok"})
            continue
        start, end, _, day, used = pl.allocate(need, day, used, P["cap"], P["week_days"])
        late = bool(w["due_date"]) and end.isoformat() > w["due_date"]
        sched.append({"w": w, "rem": rem, "need": need, "start": start, "end": end,
                      "state": "Gecikir" if late else "Zamanında"})
    load_h = sum(s["need"] for s in sched) / 60
    last_end = max((s["end"] for s in sched if s["end"]), default=None)

    kpis([
        {"icon": "◷", "color": "blue", "label": "Günlük Kapasite", "value": f"{num(P['cap'] / 60)} saat"},
        {"icon": "▦", "color": "green", "label": "Haftalık Kapasite",
         "value": f"{num(P['cap'] * P['week_days'] / 60)} saat"},
        {"icon": "%", "color": "yellow", "label": "Buffer", "value": f"%{num(P['buffer'])}"},
        {"icon": "↗", "color": "purple", "label": "Açık Sipariş Yükü",
         "value": f"{num(load_h)} saat", "change": f"Bitiş: {dmy(last_end)}" if last_end else "", "trend": "flat"},
    ])

    # ---- varsayımlar
    with st.container(key="card_plan_params"):
        card_title("Planlama Varsayımları")
        with st.form("plan_form", border=False):
            c1, c2, c3, c4 = st.columns(4)
            hours = c1.number_input("Günlük çalışma (saat)", min_value=0.5, max_value=24.0,
                                    value=P["hours"], step=0.5)
            workers = c2.number_input("Çalışan / tezgâh sayısı", min_value=1, max_value=100,
                                      value=P["workers"], step=1,
                                      help="Aynı anda çalışan kişi/tezgâh sayısı; günlük kapasiteyi çarpar.")
            wd_keys = list(WEEKDAYS)
            wdays = c3.selectbox("Çalışma günleri", wd_keys, format_func=WEEKDAYS.get,
                                 index=wd_keys.index(P["week_days"]) if P["week_days"] in wd_keys else 0)
            buf = c4.number_input("Buffer (%)", min_value=0.0, max_value=200.0, value=P["buffer"], step=5.0,
                                  help="Operasyon sürelerine eklenen pay: hazırlık, bekleme, fire, hata.")
            if st.form_submit_button("Kaydet", type="primary"):
                db.set_settings({"plan_daily_hours": hours, "plan_workers": workers,
                                 "plan_week_days": wdays, "plan_buffer_pct": buf})
                flash("Planlama varsayımları kaydedildi.")
                st.rerun()
        st.caption(f"Günlük kapasite = {num(P['hours'])} saat × {P['workers']} çalışan = "
                   f"{num(P['cap'] / 60)} saat. Buffer'lı süre = operasyon süresi × (1 + %{num(P['buffer'])}).")

    # ---- ürün bazında kapasite
    with st.container(key="card_plan_products"):
        h = st.columns([3, 2], vertical_alignment="center")
        with h[0]:
            card_title("Ürün Bazında Üretim Kapasitesi")
        local = h[1].text_input("Ürün ara", placeholder="Ürün ara...", label_visibility="collapsed", key="plan_q")
        rows = []
        for p in products:
            base = float(p["total_minutes"] or 0)
            unit = pl.buffered(base, P["buffer"])
            rows.append({
                "id": p["id"], "Kod": p["code"], "Ürün": p["name"], "Operasyon": p["operation_count"],
                "Operasyon Süresi": f"{num(base)} dk" if base else "-",
                "Buffer'lı Süre": f"{num(unit)} dk" if base else "-",
                "Günlük Adet": str(pl.per_day(P["cap"], unit)) if base else "-",
                "Haftalık Adet": str(pl.per_week(P["cap"], P["week_days"], unit)) if base else "-",
                "Durum": "Hazır" if base else "Operasyon yok",
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = search_filter(df, local, q)
        data_table(df, "plan_products",
                   ["Kod", "Ürün", "Operasyon", "Operasyon Süresi", "Buffer'lı Süre", "Günlük Adet",
                    "Haftalık Adet", "Durum"],
                   status_cols=("Durum",), status_colors={"Hazır": "green", "Operasyon yok": "gray"},
                   selectable=False, title="Üretim Kapasitesi")
        if not products:
            st.caption("Önce **Ürünler** sayfasından ürün ve operasyonlarını ekleyin.")
        else:
            st.caption("Süreler ürünün Operasyonlar sekmesindeki toplam süreden gelir. "
                       "Operasyonu olmayan ürünler için plan çıkarılamaz.")

    # ---- hesaplayıcı
    ready = [p for p in products if (p["total_minutes"] or 0) > 0]
    with st.container(key="card_plan_calc"):
        card_title("Üretim Hesaplayıcı")
        if not ready:
            st.caption("Operasyon süresi girilmiş ürün yok.")
        else:
            c1, c2, c3 = st.columns([2.5, 1, 1.4])
            prod = c1.selectbox("Ürün", ready, format_func=lambda p: f"{p['code']} · {p['name']}", key="plan_prod")
            qty = c2.number_input("Adet", min_value=1, value=10, step=1, key="plan_qty")
            start_on = c3.date_input("Başlangıç", value=date.today(), format="DD.MM.YYYY", key="plan_start")
            unit = pl.buffered(prod["total_minutes"], P["buffer"])
            total = qty * unit
            start, end, chunks, _, _ = pl.allocate(total, start_on, 0.0, P["cap"], P["week_days"])
            done = pl.units_done_by_day(chunks, unit)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Toplam süre", f"{num(total / 60)} saat")
            m2.metric("İş günü", f"{len(chunks)} gün")
            m3.metric("Bitiş tarihi", dmy(end))
            m4.metric("Günlük / haftalık", f"{pl.per_day(P['cap'], unit)} / {pl.per_week(P['cap'], P['week_days'], unit)} adet")
            st.caption(f"1 adet: {num(prod['total_minutes'])} dk + %{num(P['buffer'])} buffer = {num(unit)} dk")
            if chunks:
                ddf = pd.DataFrame([{"id": i, "Tarih": dmy(d), "Çalışma": f"{num(m / 60)} saat",
                                     "Gün Sonu Tamamlanan": f"{done[i]} adet"} for i, (d, m) in enumerate(chunks)])
                data_table(ddf, "plan_days", ["Tarih", "Çalışma", "Gün Sonu Tamamlanan"], selectable=False,
                           title=f"{prod['name']} - {qty} adet plan")

    # ---- açık siparişler
    with st.container(key="card_plan_orders"):
        card_title("Açık Siparişler İçin Plan")
        st.caption("Bekleyen ve üretimdeki siparişler termin sırasına göre, bugünden başlayarak tek hat halinde "
                   "planlanır. Tamamlanan ilerleme (%) düşülür.")
        odf = pd.DataFrame([{
            "id": s["w"]["id"], "Sipariş": s["w"]["code"], "Ürün": s["w"]["product"] or "-",
            "Kalan Adet": f"{s['rem']} adet", "Gereken Süre": f"{num(s['need'] / 60)} saat" if s["need"] else "-",
            "Başlangıç": dmy(s["start"]) if s["start"] else "-", "Bitiş": dmy(s["end"]) if s["end"] else "-",
            "Termin": dmy(s["w"]["due_date"]), "Durum": s["state"],
        } for s in sched])
        if not odf.empty:
            odf = search_filter(odf, q)
        data_table(odf, "plan_orders",
                   ["Sipariş", "Ürün", "Kalan Adet", "Gereken Süre", "Başlangıç", "Bitiş", "Termin", "Durum"],
                   status_cols=("Durum",),
                   status_colors={"Zamanında": "green", "Gecikir": "red", "Operasyon yok": "gray"},
                   selectable=False, title="Açık Siparişler Planı")
        if not orders:
            st.caption("Açık sipariş yok.")
