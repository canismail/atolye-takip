from __future__ import annotations

import io
from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from core import db, metrics
from core.ui import card_title, data_table, esc, info_rows, kpis, progress, search_filter
from core.utils import MONTHS_LONG, MONTHS_SHORT, is_hidden, month_label, money, num


def _excel(sheets: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name, df in sheets.items():
            (df if not df.empty else pd.DataFrame({"Bilgi": ["Kayıt yok"]})).to_excel(xw, sheet_name=name[:31], index=False)
            ws = xw.sheets[name[:31]]
            for col in ws.columns:
                width = max(len(str(c.value or "")) for c in col) + 2
                ws.column_dimensions[col[0].column_letter].width = min(max(width, 10), 45)
    return buf.getvalue()


def _top_df(year: str) -> pd.DataFrame:
    rows = metrics.top_products(year)
    return pd.DataFrame([{"Kod": r["code"], "Ürün": r["name"], "Adet": r["qty"], "Ciro": r["revenue"]} for r in rows])


def _summary_df(year: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "Ay": month_label(r["month"]), "Satış": r["sales"], "Gelir": r["income"],
        "Üretim Maliyeti": r["production"], "Personel": r["personnel"], "Diğer Giderler": r["other"],
        "Net": r["net"]} for r in metrics.monthly_summary(year)])


def render(q: str = "") -> None:
    S = db.get_settings()
    cur = metrics.this_month()
    years = metrics.years_with_data()

    target = float(S.get("sales_target") or 0)
    cap = float(S.get("capacity_hours") or 0)
    tt = float(S.get("turnover_target") or 0)
    sales_m = metrics.sales_total(cur)
    hours = metrics.production_hours(cur)
    turnover = metrics.stock_turnover(str(date.today().year))

    c = st.columns(3)
    boxes = [
        ("Satış Raporu", money(sales_m), f"Bu ay toplam satış · hedef {money(target)}",
         sales_m / target * 100 if target else 0),
        ("Üretim", f"{num(hours, 1)} saat", f"Bu ay gerçekleşen operasyon · kapasite {num(cap)} saat",
         hours / cap * 100 if cap else 0),
        ("Stok Devir", f"{num(turnover, 1)}x", f"Yıllık stok devir oranı · hedef {num(tt, 1)}x",
         turnover / tt * 100 if tt else 0),
    ]
    for i, (col, (label, value, sub, p)) in enumerate(zip(c, boxes)):
        with col.container(key=f"card_rep_box{i}"):
            st.markdown(f'<div class="erp-klabel">{esc(label)}</div><div class="erp-kvalue">{esc(value)}</div>'
                        f'<p class="erp-small" style="margin-top:8px">{esc(sub)}</p>'
                        f'<div style="margin-top:12px">{progress(p)}</div>'
                        f'<p class="erp-small" style="margin-top:6px">%{num(p, 0)}</p>', unsafe_allow_html=True)
    st.caption("Hedefler Ayarlar sayfasından değiştirilebilir.")

    left, right = st.columns([1.5, 1])
    with left.container(key="card_rep_top"):
        h = st.columns([2, 1, 1.2], vertical_alignment="center")
        with h[0]:
            card_title("En Çok Satan Ürünler")
        year = h[1].selectbox("Yıl", years, key="rep_year_top", label_visibility="collapsed")
        top = _top_df(year)
        h[2].download_button("Excel'e Aktar", data=_excel({"En Çok Satan": top}), disabled=is_hidden(),
                             file_name=f"en_cok_satan_{year}.xlsx", width="stretch",
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        if not top.empty:
            top["id"] = range(len(top))
            top = search_filter(top, q)
        data_table(top, "rep_top", ["Ürün", "Adet", "Ciro"], money_cols=("Ciro",), selectable=False,
                   column_config={"Adet": st.column_config.NumberColumn(format="%g")},
                   title=f"En Çok Satan Ürünler {year}")

    with right.container(key="card_rep_month"):
        h = st.columns([1.6, 1, 1.2], vertical_alignment="center")
        with h[0]:
            card_title("Aylık Özet")
        y2 = h[1].selectbox("Yıl", years, key="rep_year_sum", label_visibility="collapsed")
        opts = ["Yıl Toplamı"] + MONTHS_LONG
        default = date.today().month if y2 == str(date.today().year) else 0
        m = h[2].selectbox("Ay", opts, index=default, key="rep_month", label_visibility="collapsed")
        summ = metrics.monthly_summary(y2)
        if m == "Yıl Toplamı":
            agg = {k: sum(r[k] for r in summ) for k in ("sales", "income", "production", "personnel", "other", "net")}
        else:
            agg = summ[MONTHS_LONG.index(m)]
        net_cls = "income" if agg["net"] >= 0 else "expense"
        st.markdown(info_rows([
            ("Satış", money(agg["sales"])),
            ("Tahsil Edilen Gelir", money(agg["income"])),
            ("Üretim Maliyeti", money(agg["production"])),
            ("Personel", money(agg["personnel"])),
            ("Diğer Giderler", money(agg["other"])),
            ("Net", f'<span class="{net_cls}">{money(agg["net"])}</span>'),
        ]), unsafe_allow_html=True)
        st.caption("Üretim maliyeti: Malzeme, Enerji ve Bakım gider kategorileri.")

    with st.container(key="card_rep_trend"):
        h = st.columns([3, 1.3], vertical_alignment="center")
        with h[0]:
            card_title(f"{y2} Gelir / Gider Trendi")
        full = _summary_df(y2)
        sales_df = pd.DataFrame(db.query(
            """SELECT s.code AS "Satış No", s.date AS Tarih, c.name AS Müşteri, p.name AS Ürün,
                      s.quantity AS Adet, s.unit_price AS "Birim Fiyat", s.amount AS Tutar,
                      s.status AS Durum, s.due_date AS Vade
               FROM sales s LEFT JOIN customers c ON c.id=s.customer_id LEFT JOIN products p ON p.id=s.product_id
               WHERE substr(s.date,1,4)=? ORDER BY s.date""", (y2,)))
        tx_df = pd.DataFrame(db.query(
            """SELECT date AS Tarih, type AS Tür, category AS Kategori, description AS Açıklama,
                      doc_no AS "Belge No", amount AS Tutar FROM transactions
               WHERE substr(date,1,4)=? ORDER BY date""", (y2,)))
        stock_df = pd.DataFrame([{"Kod": s["code"], "Ad": s["name"], "Kategori": s["category"], "Birim": s["unit"],
                                  "Mevcut": s["quantity"], "Min.": s["min_qty"], "Durum": s["status"],
                                  "Birim Maliyet": s["unit_cost"], "Stok Değeri": s["value"]}
                                 for s in db.stock_items(in_stock=True, with_products=True)])
        h[1].download_button("Tüm Raporu Excel'e Aktar", disabled=is_hidden(),
                             data=_excel({"Aylık Özet": full, "En Çok Satan": _top_df(y2), "Satışlar": sales_df,
                                          "Gelir-Gider": tx_df, "Stok": stock_df}),
                             file_name=f"atolye_rapor_{y2}.xlsx", width="stretch",
                             mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        summ = metrics.monthly_summary(y2)
        long = []
        for i, r in enumerate(summ):
            long.append({"Ay": MONTHS_SHORT[i], "Seri": "Gelir", "Tutar": r["income"]})
            long.append({"Ay": MONTHS_SHORT[i], "Seri": "Gider", "Tutar": r["production"] + r["personnel"] + r["other"]})
        ldf = pd.DataFrame(long)
        ldf["Etiket"] = ldf["Tutar"].apply(money)
        chart = (
            alt.Chart(ldf).mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("Ay:N", sort=MONTHS_SHORT, title=None, axis=alt.Axis(labelAngle=0, ticks=False, domain=False)),
                xOffset=alt.XOffset("Seri:N", sort=["Gelir", "Gider"]),
                y=alt.Y("Tutar:Q", title=None, axis=alt.Axis(format="~s", gridColor="#edf1f5", domain=False, ticks=False)),
                color=alt.Color("Seri:N", scale=alt.Scale(domain=["Gelir", "Gider"], range=["#14915b", "#d64545"]),
                                legend=alt.Legend(orient="top", title=None)),
                tooltip=["Ay:N", "Seri:N", alt.Tooltip("Etiket:N", title="Tutar")],
            )
            .properties(height=260).configure_view(strokeWidth=0)
        )
        if is_hidden():
            st.caption("Grafik gizli (hassas veri). Sağ üstten **🔒 Göster** ile açın.")
        else:
            st.altair_chart(chart, use_container_width=True)
