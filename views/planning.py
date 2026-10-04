"""Üretim Planı: ürünlerin operasyon sürelerine (+ buffer) göre günlük/haftalık üretilebilecek
adet, belirli bir adet için gereken süre/bitiş tarihi ve açık siparişlerin sıralı iş takvimi."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from core import db, machine_plan as mp, planning as pl, remote
from core.ui import card_title, data_table, esc, flash, kpis, search_filter
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


def _render_general(q: str = "") -> None:
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


# ---------------------------------------------------------------- makine bazlı plan 
def _order_specs(orders: list[dict], buffer: float) -> tuple[list[mp.OrderSpec], dict]:
    ops_cache: dict[int, list[mp.OpSpec]] = {}
    specs = []
    for w in orders:
        pid = w["product_id"]
        if pid not in ops_cache:
            ops_cache[pid] = [mp.OpSpec(o["name"], float(o["minutes"] or 0), float(o.get("setup_minutes") or 0),
                                        o.get("machine_type") or mp.ANY, key=o["id"])
                              for o in db.product_operations(pid)] if pid else []
        specs.append(mp.OrderSpec(w["id"], w["code"], w["product"] or "-",
                                  pl.remaining_units(w["quantity"], w["progress"]), w["due_date"], ops_cache[pid]))
    return specs, ops_cache


def _shift_min(S: dict) -> int:
    try:
        h, m = str(S.get("plan_shift_start") or "08:00").split(":")
        return int(h) * 60 + int(m)
    except ValueError:
        return 8 * 60


def _when(t: float, d, shift: int = 8 * 60) -> str:
    return f"{dmy(d)} {mp.clock(t, shift)}"


def _stat(label: str, big: str, small: str = "") -> str:
    """Belirgin değer kutusu: etiket küçük gri, değer iri ve kalın, saat ince/yan yazı."""
    sm = (f'<span style="font-size:18px;font-weight:400;color:#556070;margin-left:8px;'
          f'font-family:ui-monospace,Menlo,monospace">{esc(small)}</span>' if small else "")
    return (f'<div style="border:1px solid #e3e8ef;border-radius:10px;padding:12px 16px;background:#fff">'
            f'<div style="font-size:12px;color:#687587;text-transform:uppercase;letter-spacing:.04em">{esc(label)}</div>'
            f'<div style="font-size:26px;font-weight:700;color:#1a2433;line-height:1.3">{esc(big)}{sm}</div></div>')


_WD = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]
_PALETTE = [("#e8f2ff", "#1673d1"), ("#e4f7ed", "#11784d"), ("#fff2d3", "#946800"), ("#eee8ff", "#6b4fd1"),
            ("#ffe7e7", "#d33e3e"), ("#e0f7f7", "#12757a"), ("#fde8f3", "#b0306f"), ("#eef0f3", "#556070")]


def _grid(plan: dict, shift: int = 8 * 60, max_days: int = 14) -> None:
    """Gün bazlı tablo: satırlar makineler, sütunlar iş günleri, hücrelerde o gün o makinede yapılacak işler."""
    if not plan["end"]:
        return
    cal = plan["calendar"]
    days, i = [], 0
    while len(days) < max_days:
        d = cal.date_of(i)
        days.append(d)
        i += 1
        if d >= plan["end"]:
            break
    cells: dict = {}
    colors: dict = {}
    for e in plan["orders"]:
        for it in e["items"]:
            key = (e["label"], it["stage"])
            c = colors.setdefault(key, _PALETTE[len(colors) % len(_PALETTE)])
            for d, a0, a1 in it["segments"]:
                cells.setdefault((it["machine_id"], d), []).append((a0, a1, it, e["label"], c))
    head = "".join(
        f'<th style="padding:8px 10px;text-align:left;border-bottom:2px solid #d9dfe7;white-space:nowrap">'
        f'{_WD[d.weekday()]} {d.strftime("%d.%m")}{" · bugün" if d == date.today() else ""}</th>' for d in days)
    body = []
    for mc in plan["machines"]:
        tds = [f'<td style="padding:8px 10px;font-weight:600;white-space:nowrap;border-bottom:1px solid #eef0f3;'
               f'vertical-align:top">{esc(mc["name"])}<div style="font-weight:400;color:#687587;font-size:12px">'
               f'{num(mc["daily_hours"])} saat/gün</div></td>']
        for d in days:
            items = sorted(cells.get((mc["id"], d), []), key=lambda x: x[0])
            if not items:
                tds.append('<td style="padding:8px 10px;color:#aab3bf;border-bottom:1px solid #eef0f3;'
                           'vertical-align:top">—</td>')
                continue
            used = sum(a1 - a0 for a0, a1, *_ in items)
            blocks = "".join(
                f'<div style="background:{c[0]};border-left:4px solid {c[1]};border-radius:6px;padding:5px 8px;'
                f'margin-bottom:5px;font-size:13px;line-height:1.35">'
                f'<b>{mp.hm(a0, shift)}–{mp.hm(a1, shift)}</b> · {esc(it["op"])}'
                f'<div style="color:#556070;font-size:12px">{esc(lbl)}</div></div>'
                for a0, a1, it, lbl, c in items)
            tds.append(f'<td style="padding:8px 10px;border-bottom:1px solid #eef0f3;vertical-align:top;min-width:170px">'
                       f'{blocks}<div style="color:#687587;font-size:11px">dolu {num(used / 60)} / '
                       f'{num(mc["daily_hours"])} sa</div></td>')
        body.append("<tr>" + "".join(tds) + "</tr>")
    st.markdown(
        '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%;font-size:14px">'
        f'<thead><tr><th style="padding:8px 10px;text-align:left;border-bottom:2px solid #d9dfe7">Makine</th>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>', unsafe_allow_html=True)
    if plan["end"] > days[-1]:
        st.caption(f"İlk {len(days)} iş günü gösteriliyor; plan {dmy(plan['end'])} tarihine kadar sürüyor.")


_BOARD = None


def _board_component():
    global _BOARD
    if _BOARD is None:
        import streamlit.components.v1 as components
        _BOARD = components.declare_component(
            "plan_board", path=str(Path(__file__).resolve().parent.parent / "components" / "plan_board"))
    return _BOARD


def _board(plan: dict, shift: int, week_days: int) -> None:
    """Sürükle-bırak çizelge: bir operasyon kutusunu başka makineye / güne sürükleyince elle yerleştirme kaydedilir,
    süreler (makinenin ayarlama süresi dahil) ve sonraki işler yeniden hesaplanır."""
    if not plan["end"]:
        return
    cal = plan["calendar"]
    days, i = [], 0
    last = plan["end"] + timedelta(days=2)
    while len(days) < 21:
        d = cal.date_of(i)
        days.append(d)
        i += 1
        if d >= last and len(days) >= 7:
            break
    iso = {d: d.isoformat() for d in days}
    colors: dict = {}
    blocks = []
    for e in plan["orders"]:
        for it in e["items"]:
            c = colors.setdefault((e["label"], it["op"]), _PALETTE[len(colors) % len(_PALETTE)])
            note = ""
            if it["forced"] and it["req_day"] and it["start_date"] != it["req_day"]:
                note = (f"İstenen gün {dmy(it['req_day'])}; önceki operasyon ya da makine dolu olduğu için "
                        f"{dmy(it['start_date'])} günü başlıyor.")
            for k, (d, a0, a1) in enumerate(it["segments"]):
                if d not in iso:
                    continue
                first = k == 0
                blocks.append({
                    "key": f"{e['key']}:{it['op_key']}", "machine_id": it["machine_id"], "day": iso[d], "order": a0,
                    "time": f"{mp.hm(a0, shift)}–{mp.hm(a1, shift)}", "label": it["op"] + ("" if first else " (devam)"),
                    "sub": e["label"], "bg": c[0], "border": c[1],
                    "draggable": first and it["op_key"] is not None, "pinned": it["forced"] and first,
                    "cont": not first, "note": note})
    model = {
        "days": [{"iso": iso[d], "label": f"{_WD[d.weekday()]} {d.strftime('%d.%m')}", "today": d == date.today()}
                 for d in days],
        "machines": [{"id": m["id"], "name": m["name"], "hours": num(m["daily_hours"])} for m in plan["machines"]],
        "blocks": blocks,
        "hint": "Bir kutuyu başka bir makineye ya da güne sürükleyip bırakın; süreler ve sonraki işler yeniden hesaplanır. "
                "📌 elle yerleştirilmiş işi gösterir.",
    }
    ev = _board_component()(model=model, key="plan_board", default=None)
    if ev and ev.get("nonce") != st.session_state.get("_pb_nonce"):
        st.session_state["_pb_nonce"] = ev["nonce"]
        try:
            wo, op = (int(x) for x in str(ev["key"]).split(":"))
            db.set_plan_override(wo, op, int(ev["machine_id"]), str(ev["day"]))
        except (ValueError, KeyError):
            return
        flash("İş yeni yerine taşındı, plan yeniden hesaplandı.")
        st.rerun()

    forced = [(e, it) for e in plan["orders"] for it in e["items"] if it["forced"]]
    if forced:
        with st.expander(f"📌 Elle yapılan değişiklikler ({len(forced)})"):
            for e, it in forced:
                c1, c2 = st.columns([5, 1], vertical_alignment="center")
                c1.markdown(f"**{e['label']}** · {it['op']} → {it['machine']} · "
                            f"{dmy(it['start_date'])} {mp.clock(it['start'], shift)}")
                if c2.button("Kaldır", key=f"ov_rm_{e['key']}_{it['op_key']}"):
                    db.clear_plan_override(int(e["key"]), int(it["op_key"]))
                    st.rerun()
            if st.button("Hepsini sıfırla (otomatik plana dön)", key="ov_reset_all"):
                db.clear_plan_overrides()
                st.session_state.pop("_pb_nonce", None)
                st.rerun()


def _gantt(plan: dict, shift: int = 8 * 60) -> None:
    rows = []
    for e in plan["orders"]:
        for it in e["items"]:
            d0, d1 = it["start_date"], it["end_date"]
            rows.append({"Makine": it["machine"], "Sipariş": e["label"], "Operasyon": it["op"],
                         "Başlangıç": pd.Timestamp(d0) + pd.Timedelta(minutes=shift + it["start"] % mp.DAY),
                         "Bitiş": pd.Timestamp(d1) + pd.Timedelta(minutes=shift + it["end"] % mp.DAY)})
    if not rows:
        return
    try:
        import altair as alt
    except ImportError:
        return
    df = pd.DataFrame(rows)
    chart = (alt.Chart(df).mark_bar(cornerRadius=3)
             .encode(x=alt.X("Başlangıç:T", title=None), x2="Bitiş:T", y=alt.Y("Makine:N", title=None),
                     color=alt.Color("Sipariş:N"), tooltip=["Sipariş", "Operasyon", "Makine", "Başlangıç", "Bitiş"])
             .properties(height=max(120, 46 * df["Makine"].nunique())))
    st.altair_chart(chart, width="stretch")
    st.caption("Çubuklar işin makinede geçtiği aralığı gösterir; gece ve hafta sonu boşlukları işin ertesi iş gününe "
               "devrettiğini gösterir.")


def _render_machines(q: str = "") -> None:
    S = db.get_settings()
    week_days = int(float(S.get("plan_week_days") or 5))
    buffer = float(S.get("plan_buffer_pct") or 0)
    machines = db.machines_list()
    active = [m for m in machines if m["active"]]
    if not machines:
        st.info("Önce **Makineler** sayfasından makine tanımlayın.")
        return

    shift = _shift_min(S)
    c1, c2, c3 = st.columns([1.2, 1.6, 2.2], vertical_alignment="center")
    new_shift = c1.time_input("Vardiya başlangıcı", value=time(shift // 60, shift % 60), step=900, key="mp_shift")
    from_now = c2.checkbox("Bugünü şu andan başlat", value=False, key="mp_now",
                           help="Açıksa bugünkü işler şu anki saatten sonra başlar; kapalıysa vardiya başlangıcından.")
    if (new_shift.hour * 60 + new_shift.minute) != shift:
        db.set_settings({"plan_shift_start": new_shift.strftime("%H:%M")})
        st.rerun()
    c3.caption("Makinelerin günlük çalışma saatleri **Makineler** sayfasından ayarlanır.")
    offset = 0.0
    if from_now and mp.is_workday(date.today(), week_days):
        now = datetime.now()
        offset = max(0.0, now.hour * 60 + now.minute - shift)

    orders = [w for w in db.work_orders_list() if w["status"] in ("Bekliyor", "Üretimde")]
    specs, _ = _order_specs(orders, buffer)
    ovs = {}
    for r in db.plan_overrides():
        try:
            ovs[(r["work_order_id"], r["op_id"])] = (r["machine_id"], date.fromisoformat(r["day"]) if r["day"] else None)
        except ValueError:
            pass
    plan = mp.schedule(specs, machines, date.today(), week_days, buffer, offset, ovs)
    late = sum(1 for e in plan["orders"] if e["state"] == "Gecikir")

    kpis([
        {"icon": "▣", "color": "blue", "label": "Aktif Makine", "value": f"{len(active)} / {len(machines)}"},
        {"icon": "◷", "color": "green", "label": "Günlük Makine Saati",
         "value": f"{num(sum(m['daily_hours'] for m in active))} saat"},
        {"icon": "!", "color": "red" if late else "green", "label": "Geciken Sipariş", "value": num(late)},
        {"icon": "↗", "color": "purple", "label": "Plan Bitişi", "value": dmy(plan["end"]) if plan["end"] else "-"},
    ])
    st.caption(f"Çalışma günleri ve buffer (%{num(buffer)}) **Genel Kapasite** sekmesindeki varsayımlardan alınır. "
               "Süre = parça ayarlama (makine varsayılanı, genelde 2 saat) + adet × operasyon süresi × (1 + buffer). "
               "Pasif makineler plana girmez.")

    for e in plan["orders"]:
        if e["state"] == "Makine yok":
            st.warning(f"**{e['label']}** planlanamadı: “{e['blocked_op']}” operasyonu için "
                       f"{('“' + e['blocked_type'] + '” türünde ') if e['blocked_type'] else ''}aktif makine yok.")

    # ---- günlük çizelge: hangi makinede ne zaman ne var
    with st.container(key="card_mplan_daily"):
        card_title("Günlük Çizelge")
        _board(plan, shift, week_days)
        cal = plan["calendar"]
        days = [cal.date_of(i) for i in range(10)]
        dsel = st.selectbox("Gün", days, format_func=lambda d: dmy(d) + (" (bugün)" if d == date.today() else ""),
                            key="mp_day")
        rows = []
        for mc in plan["machines"]:
            mine = []
            for e in plan["orders"]:
                for it in e["items"]:
                    if it["machine_id"] != mc["id"]:
                        continue
                    for d, a0, a1 in it["segments"]:
                        if d == dsel:
                            note = ""
                            if it["start_date"] < dsel:
                                note = "dünden devam"
                            if it["end_date"] > dsel:
                                note = (note + " · " if note else "") + "ertesi gün devam"
                            mine.append((a0, {"id": len(rows) + len(mine), "Makine": mc["name"], "Sipariş": e["label"],
                                              "Operasyon": it["op"],
                                              "Başlangıç": mp.hm(a0, shift), "Bitiş": mp.hm(a1, shift),
                                              "Not": note}))
            if mine:
                rows += [r for _, r in sorted(mine, key=lambda x: x[0])]
            else:
                rows.append({"id": len(rows), "Makine": mc["name"], "Sipariş": "-", "Operasyon": "Boş",
                             "Başlangıç": "-", "Bitiş": "-", "Not": ""})
        data_table(pd.DataFrame(rows), "mplan_daily",
                   ["Makine", "Sipariş", "Operasyon", "Başlangıç", "Bitiş", "Not"],
                   selectable=False, title=f"Günlük Çizelge {dmy(dsel)}")
        prow = [{"id": i, "Sipariş": e["label"], "Operasyon": p["op"], "Makine": p["machine"],
                 "Tahmini Bitiş": _when(p["end"], p["end_date"], shift)}
                for i, (e, p) in enumerate((e, p) for e in plan["orders"] for p in e["parts"])]
        if prow:
            st.markdown("**Operasyonların tahmini bitişi**")
            data_table(pd.DataFrame(prow), "mplan_parts",
                       ["Sipariş", "Operasyon", "Makine", "Tahmini Bitiş"],
                       selectable=False, title="Operasyon Bitişleri")

    with st.container(key="card_mplan_orders"):
        card_title("Sipariş Planı (Makine Bazlı)")
        odf = pd.DataFrame([{
            "id": e["key"], "Sipariş": e["label"], "Ürün": e["product"], "Kalan Adet": f"{mp_int(e['qty'])} adet",
            "Toplam İş": f"{num(e['hours'])} saat" if e["hours"] else "-",
            "Başlangıç": f"{dmy(e['start'])} {mp.clock(e['start_t'], shift)}" if e["start"] else "-",
            "Bitiş": f"{dmy(e['end'])} {mp.clock(e['end_t'], shift)}" if e["end"] else "-",
            "Termin": dmy(e["due"]) if e["due"] else "-", "Durum": e["state"],
        } for e in plan["orders"]])
        if not odf.empty:
            odf = search_filter(odf, q)
        data_table(odf, "mplan_orders",
                   ["Sipariş", "Ürün", "Kalan Adet", "Toplam İş", "Başlangıç", "Bitiş", "Termin", "Durum"],
                   status_cols=("Durum",),
                   status_colors={"Zamanında": "green", "Gecikir": "red", "Operasyon yok": "gray", "Makine yok": "yellow"},
                   selectable=False, title="Makine Bazlı Sipariş Planı")
        if not orders:
            st.caption("Açık sipariş yok. Aşağıdaki simülasyonla bir ürünü deneyebilirsiniz.")

    with st.container(key="card_mplan_ops"):
        card_title("Operasyon / Makine Atamaları")
        rows = []
        for e in plan["orders"]:
            for it in e["items"]:
                rows.append({"id": len(rows), "Sipariş": e["label"], "Operasyon": it["op"], "Makine": it["machine"],
                             "Başlangıç": _when(it["start"], it["start_date"], shift), "Bitiş": _when(it["end"], it["end_date"], shift),
                             "Sök-Tak": f"{num(it['setup'])} dk" if it["setup"] else "-",
                             "Çalışma": f"{num(it['run'])} dk"})
        adf = pd.DataFrame(rows)
        if not adf.empty:
            adf = search_filter(adf, q)
        data_table(adf, "mplan_ops", ["Sipariş", "Operasyon", "Makine", "Başlangıç", "Bitiş", "Sök-Tak", "Çalışma"],
                   selectable=False, title="Operasyon Atamaları")
        _gantt(plan, shift)

    with st.container(key="card_mplan_load"):
        card_title("Makine Doluluğu (önümüzdeki iş günleri)")
        cal = plan["calendar"]
        days = [cal.date_of(i) for i in range(10)]
        lrows = []
        for m in plan["machines"]:
            cap = m["daily_hours"] * 60
            r = {"Makine": f"{m['name']} ({m['type']})"}
            for d in days:
                r[dmy(d)[:5]] = round(min(100.0, m["busy"].get(d, 0.0) / cap * 100), 0) if cap else 0
            lrows.append(r)
        if lrows:
            ldf = pd.DataFrame(lrows)
            cfg = {c: st.column_config.ProgressColumn(c, min_value=0, max_value=100, format="%d%%")
                   for c in ldf.columns if c != "Makine"}
            st.dataframe(ldf, hide_index=True, column_config=cfg, width="stretch")
        idle = [m["name"] for m in machines if not m["active"]]
        if idle:
            st.caption("Pasif (planda yok): " + ", ".join(idle))

    # ---- simülasyon
    products = [p for p in db.products_with_stats() if (p["operation_count"] or 0) > 0]
    with st.container(key="card_mplan_sim"):
        card_title("Plan Simülasyonu")
        if not products:
            st.caption("Operasyonu tanımlı ürün yok. Ürünler sayfasında Operasyonlar sekmesine makine türü ve süre girin.")
        else:
            c1, c2, c3 = st.columns([2.5, 1, 1.4])
            prod = c1.selectbox("Ürün", products, format_func=lambda p: f"{p['code']} · {p['name']}", key="msim_prod")
            qty = c2.number_input("Adet", min_value=1, value=10, step=1, key="msim_qty")
            start_on = c3.date_input("Başlangıç", value=date.today(), format="DD.MM.YYYY", key="msim_start")
            sim_ops = [mp.OpSpec(o["name"], float(o["minutes"] or 0), float(o.get("setup_minutes") or 0),
                                 o.get("machine_type") or mp.ANY)
                       for o in db.product_operations(prod["id"])]
            sim = mp.schedule([mp.OrderSpec("sim", "Simülasyon", prod["name"], qty, None, sim_ops)],
                              machines, start_on, week_days, buffer)
            e = sim["orders"][0]
            if e["state"] == "Makine yok":
                st.warning(f"“{e['blocked_op']}” için aktif makine yok.")
            elif e["state"] == "Operasyon yok":
                st.warning("Bu ürünün operasyon süresi girilmemiş.")
            else:
                m1, m2, m3 = st.columns([1, 1.3, 1.3])
                m1.markdown(_stat("Toplam iş", f"{num(e['hours'])} saat"), unsafe_allow_html=True)
                m2.markdown(_stat("Başlangıç", dmy(e["start"]), mp.clock(e["start_t"], shift)), unsafe_allow_html=True)
                m3.markdown(_stat("Bitiş", dmy(e["end"]), mp.clock(e["end_t"], shift)), unsafe_allow_html=True)
                if start_on.weekday() >= week_days:
                    st.caption(f"Seçilen başlangıç ({dmy(start_on)}) iş günü değil; plan ilk iş gününden "
                               f"({dmy(e['start'])}) başlatıldı.")
                _grid(sim, shift)
                done = pd.DataFrame([{"id": i, "Operasyon": p["op"], "Makine": p["machine"],
                                      "Tahmini Bitiş": _when(p["end"], p["end_date"], shift)}
                                     for i, p in enumerate(e["parts"])])
                data_table(done, "msim_parts", ["Operasyon", "Makine", "Tahmini Bitiş"],
                           selectable=False, title=f"{prod['name']} - operasyon bitişleri (simülasyon)")
                st.caption("Simülasyon, makineler boşmuş gibi hesaplanır; mevcut siparişlerin doluluğu hesaba katılmaz.")


def mp_int(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else num(x)


def render(q: str = "") -> None:
    t1, t2 = st.tabs(["Makine Bazlı Plan", "Genel Kapasite"])
    with t1:
        _render_machines(q)
    with t2:
        _render_general(q)
