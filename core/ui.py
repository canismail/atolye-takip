"""Tasarımdaki görünümü Streamlit'e taşıyan ortak arayüz parçaları."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Callable

import pandas as pd
import streamlit as st

from core import db
from core.pdf_export import slug, table_pdf_bytes
from core.utils import money, tr_lower

BRAND_DIR = Path(__file__).resolve().parent / "assets" / "brand"
LOGO_PATH = BRAND_DIR / "logo_full.png"
FAVICON_PATH = BRAND_DIR / "favicon.png"

PAGES = {
    "dashboard": ("⌂", "Dashboard"),
    "orders": ("↗", "Siparişler"),
    "products": ("◇", "Ürünler"),
    "materials": ("▦", "Malzeme Bileşenleri"),
    "stock": ("□", "Stok"),
    "customers": ("♙", "Müşteriler"),
    "sales": ("₺", "Satışlar"),
    "finance": ("▤", "Gelir / Gider"),
    "reports": ("▥", "Raporlar"),
    "settings": ("⚙", "Ayarlar"),
}

# Durum rozetleri: (arka plan, yazı rengi)
BADGE = {
    "green": ("#dff5e9", "#11784d"),
    "gray": ("#e9edf2", "#687587"),
    "red": ("#ffdede", "#d33e3e"),
    "yellow": ("#ffeab0", "#946800"),
    "blue": ("#e8f2ff", "#1673d1"),
}
STATUS_COLORS = {
    "Aktif": "green", "Normal": "green", "Ödendi": "green", "Gelir": "green", "Tamamlandı": "green",
    "Pasif": "gray", "İptal": "gray", "Bekliyor": "yellow",
    "Kritik": "red", "Gider": "red", "Gecikti": "red",
    "Minimuma Yakın": "yellow", "Üretimde": "blue",
}

CSS = """
<style>
:root{--nav:#172538;--blue:#1673d1;--bg:#f4f7fb;--line:#e2e8f0;--text:#172033;--muted:#68768a;
--green:#14915b;--red:#d64545;--yellow:#c58a00;--purple:#7048cf;}
html, body, [data-testid="stAppViewContainer"]{background:var(--bg);}
[data-testid="stAppViewContainer"] *:not([data-testid="stIconMaterial"]):not([class*="material"]){font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;}
[data-testid="stIconMaterial"], [class*="material-symbols"], [class*="material-icons"]{font-family:"Material Symbols Rounded","Material Symbols Outlined",monospace!important;}
[data-testid="stHeader"]{background:transparent;}
#MainMenu, footer{visibility:hidden;}
.block-container, [data-testid="stMainBlockContainer"]{padding-top:1.2rem;padding-bottom:2rem;max-width:100%;}

/* ---------- sidebar ---------- */
section[data-testid="stSidebar"]{background:var(--nav);min-width:215px!important;max-width:240px!important;}
section[data-testid="stSidebar"] *{color:#c7d1dd;}
.st-key-brand{background:#fff;border-radius:12px;padding:16px 10px 12px;margin:2px 2px 18px;text-align:center;}
.st-key-brand [data-testid="stImage"]{display:flex;justify-content:center;}
.st-key-brand img{max-width:150px!important;width:100%!important;height:auto!important;}
.st-key-nav button{justify-content:flex-start!important;border:0!important;background:transparent!important;
  color:#c7d1dd!important;padding:9px 12px!important;min-height:40px;border-radius:7px!important;box-shadow:none!important;}
.st-key-nav button p{color:inherit!important;font-size:14px;}
.st-key-nav button:hover{background:#ffffff14!important;color:#fff!important;}
.st-key-nav button[kind="primary"], .st-key-nav [data-testid="stBaseButton-primary"]{background:var(--blue)!important;color:#fff!important;}
.st-key-nav [data-testid="stVerticalBlock"]{gap:4px;}

/* ---------- topbar ---------- */
.st-key-topbar{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 18px;margin-bottom:6px;}
.erp-title{font-size:26px;font-weight:700;color:var(--text);margin:0;line-height:38px;}
.erp-profile{display:flex;align-items:center;gap:8px;justify-content:flex-end;height:38px;color:var(--text);}
.erp-avatar{width:34px;height:34px;border-radius:50%;background:#5d7fa8;color:#fff;display:grid;place-items:center;font-weight:600;font-size:13px;}

/* ---------- kartlar ---------- */
[class*="st-key-card"]{background:#fff;border:1px solid var(--line)!important;border-radius:8px!important;padding:14px 16px;}
.erp-cardtitle{font-size:17px;font-weight:700;color:var(--text);margin:4px 0;}
.erp-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:14px;}
.erp-kpis.c3{grid-template-columns:repeat(3,1fr);}
.erp-kpi{background:#fff;border:1px solid var(--line);border-radius:8px;padding:17px;min-height:105px;display:flex;align-items:center;gap:13px;}
.erp-kpi-icon{width:46px;height:46px;border-radius:50%;display:grid;place-items:center;font-size:20px;flex:none;}
.erp-klabel{font-size:12px;color:var(--muted);margin-bottom:6px;white-space:nowrap;}
.erp-kvalue{font-size:22px;font-weight:700;color:var(--text);white-space:nowrap;}
.erp-change{margin-left:auto;align-self:flex-end;font-size:11px;white-space:nowrap;}
.up{color:var(--green);} .down{color:var(--red);} .flat{color:var(--muted);}
.i-blue{background:#e8f2ff;color:var(--blue);} .i-green{background:#e4f7ed;color:var(--green);}
.i-red{background:#ffe7e7;color:var(--red);} .i-yellow{background:#fff2d3;color:var(--yellow);}
.i-purple{background:#eee8ff;color:var(--purple);}
.erp-status{display:inline-flex;padding:4px 9px;border-radius:14px;font-size:11px;font-weight:600;}
.erp-mini{width:100%;border-collapse:collapse;font-size:12.5px;}
.erp-mini td{padding:9px 6px;border-bottom:1px solid #edf1f5;color:#39485e;}
.erp-mini tr:last-child td{border-bottom:0;}
.erp-mini td.r{text-align:right;}
.income{color:var(--green)!important;font-weight:600;} .expense{color:var(--red)!important;font-weight:600;}
.erp-progress{height:8px;background:#edf1f5;border-radius:10px;overflow:hidden;}
.erp-progress span{display:block;height:100%;background:var(--blue);border-radius:10px;}
.erp-info div{display:flex;justify-content:space-between;padding:7px 0;font-size:12px;color:var(--muted);border-bottom:1px dashed #edf1f5;}
.erp-info div:last-child{border-bottom:0;}
.erp-info strong{color:#39485e;}
.erp-product-image{height:115px;border-radius:7px;background:linear-gradient(135deg,#edf3f8,#fafcff);display:grid;place-items:center;font-size:55px;margin-bottom:10px;}
.erp-pname{font-size:17px;font-weight:700;color:var(--text);}
.erp-small{font-size:11px;color:var(--muted);}
.erp-empty{padding:18px;text-align:center;color:var(--muted);font-size:13px;}
.erp-avatar-lg{width:42px;height:42px;border-radius:50%;background:#e8f2ff;color:var(--blue);display:grid;place-items:center;font-weight:700;}
@media(max-width:1200px){.erp-kpis{grid-template-columns:repeat(2,1fr);}}
@media(max-width:650px){.erp-kpis,.erp-kpis.c3{grid-template-columns:1fr;}}

/* ---------- tablo PDF indirme: küçük, sağa yaslı, grid'in hemen altında ---------- */
[class*="st-key-pdfbar"] div[data-testid="stDownloadButton"] button{
  min-height:26px!important;height:26px!important;width:26px!important;padding:0!important;
  border-radius:6px!important;border:1px solid var(--line)!important;background:#fff!important;
  color:var(--muted)!important;box-shadow:0 1px 3px rgba(16,24,40,.08)!important;font-size:13px!important;
  opacity:.55;transition:opacity .12s ease,color .12s ease,border-color .12s ease;}
[class*="st-key-pdfbar"] div[data-testid="stDownloadButton"] button:hover{
  opacity:1;background:#f4f7fb!important;color:var(--blue)!important;border-color:var(--blue)!important;}
[class*="st-key-pdfbar"] div[data-testid="stDownloadButton"] button p{margin:0!important;}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x if x is not None else ""))


# ---------------------------------------------------------------- navigasyon
def go(page: str) -> None:
    st.session_state.page = page
    st.session_state["_clear_search"] = True
    st.query_params["page"] = page


def nav_button(label: str, page: str, key: str) -> None:
    """Sayfa değiştiren buton (ör. 'Tümünü Gör')."""
    st.button(label, key=key, on_click=go, args=(page,))


# ---------------------------------------------------------------- bildirim
def flash(msg: str, icon: str = "✅") -> None:
    st.session_state.setdefault("_flash", []).append((msg, icon))


def show_flash() -> None:
    for msg, icon in st.session_state.pop("_flash", []):
        st.toast(msg, icon=icon)


def bump(name: str) -> None:
    """Tablo seçimlerini sıfırlamak için anahtar sayacını artırır."""
    st.session_state[f"_nonce_{name}"] = st.session_state.get(f"_nonce_{name}", 0) + 1


def nonce(name: str) -> int:
    return st.session_state.get(f"_nonce_{name}", 0)


# ---------------------------------------------------------------- parçalar
def kpis(items: list[dict], cols: int = 4) -> None:
    """items: {icon, color, label, value, change?, trend? ('up'|'down'|'flat')}"""
    parts = []
    for it in items:
        ch = ""
        if it.get("change"):
            ch = f'<span class="erp-change {it.get("trend", "flat")}">{esc(it["change"])}</span>'
        parts.append(
            f'<div class="erp-kpi"><div class="erp-kpi-icon i-{it["color"]}">{esc(it["icon"])}</div>'
            f'<div><div class="erp-klabel">{esc(it["label"])}</div>'
            f'<div class="erp-kvalue">{esc(it["value"])}</div></div>{ch}</div>'
        )
    cls = "erp-kpis c3" if cols == 3 else "erp-kpis"
    st.markdown(f'<div class="{cls}">{"".join(parts)}</div>', unsafe_allow_html=True)


def card_title(title: str) -> None:
    st.markdown(f'<div class="erp-cardtitle">{esc(title)}</div>', unsafe_allow_html=True)


def badge(text: str, color: str | None = None) -> str:
    bg, fg = BADGE[color or STATUS_COLORS.get(text, "gray")]
    return f'<span class="erp-status" style="background:{bg};color:{fg}">{esc(text)}</span>'


def mini_table(rows: list[list[str]], empty: str = "Kayıt yok.") -> None:
    """HTML parçaları içeren basit tablo (hücreler önceden kaçışlanmış olmalı)."""
    if not rows:
        st.markdown(f'<div class="erp-empty">{esc(empty)}</div>', unsafe_allow_html=True)
        return
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    st.markdown(f'<table class="erp-mini">{body}</table>', unsafe_allow_html=True)


def progress(pct_value: float) -> str:
    w = max(0, min(100, pct_value))
    return f'<div class="erp-progress"><span style="width:{w:.0f}%"></span></div>'


def info_rows(pairs: list[tuple[str, str]]) -> str:
    inner = "".join(f"<div><span>{esc(k)}</span><strong>{v}</strong></div>" for k, v in pairs)
    return f'<div class="erp-info">{inner}</div>'


def empty(msg: str) -> None:
    st.markdown(f'<div class="erp-empty">{esc(msg)}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------- tablo
def search_filter(df: pd.DataFrame, *terms: str) -> pd.DataFrame:
    """Tüm sütunlarda (Türkçe harf duyarlı, büyük/küçük duyarsız) arama."""
    terms = [tr_lower(t).strip() for t in terms if t and str(t).strip()]
    if df.empty or not terms:
        return df
    text = df.astype(str).apply(lambda r: tr_lower(" ".join(r.values)), axis=1)
    mask = pd.Series(True, index=df.index)
    for t in terms:
        mask &= text.str.contains(t, regex=False)
    return df[mask]


def data_table(
    df: pd.DataFrame,
    key: str,
    columns: list[str],
    status_cols: tuple[str, ...] = (),
    money_cols: tuple[str, ...] = (),
    colored_money: tuple[str, ...] = (),
    debt_cols: tuple[str, ...] = (),
    column_config: dict | None = None,
    selectable: bool = True,
    status_colors: dict | None = None,
    height: int | str = "auto",
    title: str | None = None,
):
    """st.dataframe üzerine: durum rozeti renklendirme, para biçimi, tek satır seçimi.
    df mutlaka 'id' sütunu içermeli; seçilen satırın id'si döner (yoksa None).
    colored_money: pozitif değer yeşil, negatif kırmızı gösterilen para sütunları.
    title verilirse, tablonun altına (Streamlit'in yerleşik CSV indirmesinin yanına)
    aynı veriyi PDF olarak indiren bir düğme eklenir."""
    if df.empty:
        empty("Kayıt bulunamadı.")
        return None
    colors = dict(STATUS_COLORS)
    if status_colors:
        colors.update(status_colors)
    df = df.reset_index(drop=True)
    styler = df.style

    def _status_css(v):
        c = colors.get(v)
        if not c:
            return ""
        bg, fg = BADGE[c]
        return f"background-color:{bg};color:{fg};font-weight:600"

    style_map = getattr(styler, "map", None) or styler.applymap
    for c in status_cols:
        if c in df.columns:
            styler = style_map(_status_css, subset=[c])
            style_map = getattr(styler, "map", None) or styler.applymap

    fmt = {c: (lambda v: money(v)) for c in money_cols if c in df.columns}
    if fmt:
        styler = styler.format(fmt)

    # Renkli para sütunları: pozitif yeşil, negatif kırmızı
    for c in colored_money:
        if c in df.columns:
            styler = style_map(
                lambda v: "color:#d64545;font-weight:600" if (v or 0) < 0
                else ("color:#14915b;font-weight:600" if (v or 0) > 0 else ""),
                subset=[c],
            )
            style_map = getattr(styler, "map", None) or styler.applymap
            styler = styler.format({c: lambda v: money(v)})
    # Borç sütunları: >0 kırmızı, 0 yeşil
    for c in debt_cols:
        if c in df.columns:
            styler = style_map(
                lambda v: "color:#d64545;font-weight:600" if (v or 0) > 0 else "color:#14915b;font-weight:600",
                subset=[c],
            )
            style_map = getattr(styler, "map", None) or styler.applymap
            styler = styler.format({c: lambda v: money(v)})

    kwargs = dict(
        hide_index=True,
        column_order=columns,
        column_config=column_config or {},
        width="stretch",
        key=f"{key}_{nonce(key)}",
    )
    if height != "auto":
        kwargs["height"] = height
    selected = None
    if selectable:
        event = st.dataframe(styler, on_select="rerun", selection_mode="single-row", **kwargs)
        rows = event.selection.rows if event and hasattr(event, "selection") else []
        if rows:
            idx = rows[0]
            if 0 <= idx < len(df):
                selected = int(df.loc[idx, "id"])
    else:
        st.dataframe(styler, **kwargs)

    if title:
        money_set = set(money_cols) | set(colored_money) | set(debt_cols)
        pdf_rows = [[money(row[c]) if c in money_set else row[c] for c in columns] for _, row in df.iterrows()]
        try:
            company = db.get_setting("company_name")
        except Exception:
            company = ""
        pdf_bytes = table_pdf_bytes(title, list(columns), pdf_rows, company=company)
        with st.container(key=f"pdfbar_{key}_{nonce(key)}"):
            bar = st.columns([12, 1])
            with bar[1]:
                st.download_button("⬇", data=pdf_bytes, file_name=f"{slug(title)}.pdf",
                                   mime="application/pdf", key=f"{key}_pdf_{nonce(key)}",
                                   help="PDF olarak indir")
    return selected


def confirm_delete(key: str, label: str, on_confirm: Callable[[], str | None]) -> None:
    """İki adımlı silme: önce 'Sil', sonra 'Evet, sil'."""
    flag = f"_confirm_{key}"
    if not st.session_state.get(flag):
        if st.button("🗑 Sil", key=f"{key}_ask", type="secondary"):
            st.session_state[flag] = True
            st.rerun()
        return
    st.warning(f"**{label}** silinsin mi? Bu işlem geri alınamaz.")
    c1, c2 = st.columns(2)
    if c1.button("Evet, sil", key=f"{key}_yes", type="primary", width="stretch"):
        st.session_state[flag] = False
        err = on_confirm()
        if err:
            st.error(err)
        else:
            flash(f"{label} silindi.", "🗑")
            st.rerun()
    if c2.button("Vazgeç", key=f"{key}_no", width="stretch"):
        st.session_state[flag] = False
        st.rerun()
