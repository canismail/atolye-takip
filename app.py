"""Atölye Yönetim Paneli — Streamlit uygulaması.

Çalıştırmak için:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from core import db, remote
from core.ui import FAVICON_PATH, LOGO_PATH, PAGES, esc, go, inject_css, show_flash
from core import privacy
from core.utils import dmy, initials, money, set_currency, set_hidden
from views import (customers, dashboard, finance, machines, materials, orders, planning, products,
                   reports, sales, settings, stock)

st.set_page_config(page_title="Atölye Yönetim Paneli", page_icon=str(FAVICON_PATH), layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- çalışma kipi (sunucu / yerel)
def _switch_mode(m: str) -> None:
    remote.set_mode(m)
    st.session_state.pop("db_ready", None)  # yeni kipte veritabanı yeniden hazırlanır


def _mode_toggle(key: str) -> None:
    if not remote.available():
        return
    label = st.radio("Veri kaynağı", ["🌐 Sunucu", "💻 Yerel"], index=0 if remote.enabled() else 1,
                     horizontal=True, key=key)
    want = "server" if label.startswith("🌐") else "local"
    if want != remote.mode():
        _switch_mode(want)
        st.rerun()


# ---------------------------------------------------------------- sunucu girişi (merkezi veritabanı)
def _login_screen() -> None:
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("### Atölye Yönetim")
        st.caption(f"Sunucu: {remote.server_url()}")
        _mode_toggle("mode_login")
        with st.form("login_form"):
            user = st.text_input("Kullanıcı adı")
            pw = st.text_input("Şifre", type="password")
            if st.form_submit_button("Giriş yap", type="primary", width="stretch"):
                try:
                    remote.login(user, pw)
                    st.rerun()
                except remote.RemoteError as exc:
                    st.error(str(exc))


if remote.enabled():
    if not remote.logged_in():
        try:
            remote.auto_login()
        except remote.RemoteError as exc:
            st.error(str(exc))
    if not remote.logged_in():
        _login_screen()
        st.stop()
    try:
        db.begin_run()  # sunucudaki güncel veriyi alır
    except remote.RemoteError as exc:
        if not remote.logged_in():
            st.rerun()
        st.error(str(exc))
        st.button("Tekrar dene")
        st.stop()

# ---------------------------------------------------------------- başlangıç
if "db_ready" not in st.session_state:
    db.init_db()
    try:
        db.auto_backup_if_due()
    except Exception as exc:  # yedekleme uygulamayı durdurmasın
        st.session_state["_backup_error"] = str(exc)
    st.session_state.db_ready = True

S = db.get_settings()
set_currency(S.get("currency", "TRY"))
inject_css()

if "page" not in st.session_state:
    qp = st.query_params.get("page", "dashboard")
    st.session_state.page = qp if qp in PAGES else "dashboard"
st.session_state.setdefault("global_search", "")
if st.session_state.pop("_clear_search", False):
    st.session_state.global_search = ""

VIEWS = {
    "dashboard": dashboard.render,
    "orders": orders.render,
    "planning": planning.render,
    "machines": machines.render,
    "products": products.render,
    "materials": materials.render,
    "stock": stock.render,
    "customers": customers.render,
    "sales": sales.render,
    "finance": finance.render,
    "reports": reports.render,
    "settings": settings.render,
}

# ---------------------------------------------------------------- sidebar
with st.sidebar:
    with st.container(key="brand"):
        st.image(str(LOGO_PATH))
    with st.container(key="nav"):
        for pid, (icon, label) in PAGES.items():
            st.button(f"{icon}  {label}", key=f"nav_{pid}", on_click=go, args=(pid,),
                      type="primary" if st.session_state.page == pid else "secondary",
                      width="stretch")


# ---------------------------------------------------------------- bildirimler
def alerts() -> list[str]:
    items: list[str] = []
    if S.get("stock_alert") == "1":
        for s in db.stock_items(in_stock=True, with_products=True):
            if s["status"] == "Kritik":
                items.append(f"🔴 Kritik stok: **{s['name']}** ({s['quantity']:g} {s['unit']}, min. {s['min_qty']:g})")
            elif s["status"] == "Minimuma Yakın":
                items.append(f"🟡 Minimuma yakın: **{s['name']}** ({s['quantity']:g} {s['unit']})")
    for r in db.query("""SELECT s.code, s.amount, s.due_date, c.name AS customer FROM sales s
                         LEFT JOIN customers c ON c.id=s.customer_id
                         WHERE s.status='Bekliyor' AND s.due_date < date('now','localtime')
                         ORDER BY s.due_date"""):
        items.append(f"💰 Vadesi geçti: **{r['code']}** {r['customer'] or ''} — {money(r['amount'])} ({dmy(r['due_date'])})")
    for r in db.query("""SELECT w.code, w.due_date, p.name AS product FROM work_orders w
                         LEFT JOIN products p ON p.id=w.product_id
                         WHERE w.status IN ('Bekliyor','Üretimde') AND w.due_date < date('now','localtime')"""):
        items.append(f"⏰ Termini geçti: **{r['code']}** {r['product'] or ''} ({dmy(r['due_date'])})")
    return items


# ---------------------------------------------------------------- topbar
@st.dialog("Gizli verileri göster")
def _unlock_dialog() -> None:
    pw = st.text_input("Şifre", type="password", placeholder="Şifre", key="priv_pw")
    c1, c2 = st.columns(2)
    if c1.button("Vazgeç", width="stretch", key="priv_cancel"):
        st.rerun()
    if c2.button("Göster", type="primary", width="stretch", key="priv_ok"):
        if privacy.check(pw):
            privacy.set_hidden(False)
            st.rerun()
        st.error("Şifre hatalı.")


set_hidden(privacy.is_hidden())
page = st.session_state.page
with st.container(key="topbar"):
    c_title, c_search, c_eye, c_bell, c_prof = st.columns([3, 3.2, 1.1, 0.8, 1.6], vertical_alignment="center")
    c_title.markdown(f'<h1 class="erp-title">{esc(PAGES[page][1])}</h1>', unsafe_allow_html=True)
    c_search.text_input("Ara", key="global_search", placeholder="Ara...  ⌕",
                        label_visibility="collapsed",
                        help="Açık sayfadaki tüm tablolarda arar")
    if not privacy.is_hidden():
        if c_eye.button("🙈 Gizle", key="priv_hide", width="stretch", help="Parasal verileri gizler"):
            privacy.set_hidden(True)
            st.rerun()
    elif c_eye.button("🔒 Göster", key="priv_show", width="stretch", help="Şifre ile gizli verileri açar"):
        _unlock_dialog()
    notes = alerts()
    with c_bell.popover(f"🔔 {len(notes)}" if notes else "🔔"):
        st.markdown("**Bildirimler**")
        if notes:
            for n in notes[:30]:
                st.markdown(n)
        else:
            st.caption("Yeni bildirim yok.")
    with c_prof.popover(f"{initials(S['user_name'])} · {S['user_name']}"):
        st.markdown(f'<div class="erp-profile" style="justify-content:flex-start">'
                    f'<div class="erp-avatar">{esc(initials(S["user_name"]))}</div>'
                    f'<div><b>{esc(S["user_name"])}</b><br><span class="erp-small">{esc(S["company_name"])}</span></div></div>',
                    unsafe_allow_html=True)
        st.button("⚙ Ayarlar", key="prof_settings", on_click=go, args=("settings",), width="stretch")
        st.button("⌂ Dashboard", key="prof_home", on_click=go, args=("dashboard",), width="stretch")
        _mode_toggle("mode_prof")
        if remote.enabled():
            st.caption(f"Sunucu: {remote.server_url()}")
            st.button("⎋ Çıkış", key="prof_logout", on_click=remote.logout, width="stretch")
        elif remote.available():
            st.caption("Yerel mod: veriler bu bilgisayardaki data/erp.db dosyasında.")

if st.session_state.pop("_backup_error", None):
    st.warning("Otomatik yedek alınamadı. Ayarlar sayfasından manuel yedek alabilirsiniz.")

show_flash()
VIEWS[page](st.session_state.global_search)
