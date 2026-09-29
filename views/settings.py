from __future__ import annotations

from datetime import datetime

import streamlit as st

from core import db
from core.ui import card_title, flash, info_rows
from core.utils import CURRENCY_SYMBOLS, num


def render(q: str = "") -> None:
    S = db.get_settings()
    left, right = st.columns([1.5, 1])

    with left.container(key="card_set_company"):
        card_title("Firma Bilgileri")
        with st.form("company_form", border=False):
            name = st.text_input("Firma Adı", value=S["company_name"])
            c1, c2 = st.columns(2)
            phone = c1.text_input("Telefon", value=S["company_phone"], placeholder="0312 000 00 00")
            email = c2.text_input("E-posta", value=S["company_email"], placeholder="info@atolye.local")
            addr = st.text_area("Adres", value=S["company_address"], height=70)
            c3, c4 = st.columns(2)
            office = c3.text_input("Vergi Dairesi", value=S["company_tax_office"])
            taxno = c4.text_input("Vergi No", value=S["company_tax_no"])
            user = st.text_input("Kullanıcı Adı (sağ üstte görünür)", value=S["user_name"])
            if st.form_submit_button("Kaydet", type="primary"):
                if not name.strip():
                    st.error("Firma adı boş olamaz.")
                elif email and "@" not in email:
                    st.error("E-posta adresi geçersiz görünüyor.")
                else:
                    db.set_settings({"company_name": name.strip(), "company_phone": phone.strip(),
                                     "company_email": email.strip(), "company_address": addr.strip(),
                                     "company_tax_office": office.strip(), "company_tax_no": taxno.strip(),
                                     "user_name": user.strip() or "Kullanıcı"})
                    flash("Firma bilgileri kaydedildi.")
                    st.rerun()

    with right.container(key="card_set_system"):
        card_title("Sistem")
        st.markdown(info_rows([
            ("Para Birimi", f"{S['currency']} ({CURRENCY_SYMBOLS.get(S['currency'], '₺')})"),
            ("Vergi Oranı", f"%{num(float(S['tax_rate'] or 0))}"),
            ("Stok Uyarısı", "Aktif" if S["stock_alert"] == "1" else "Pasif"),
            ("Otomatik Yedekleme", "Aktif" if S["auto_backup"] == "1" else "Pasif"),
            ("Son Yedek", S["last_backup"] or "-"),
        ]), unsafe_allow_html=True)
        with st.form("system_form", border=False):
            codes = list(CURRENCY_SYMBOLS)
            cur = st.selectbox("Para Birimi", codes, index=codes.index(S["currency"]) if S["currency"] in codes else 0)
            tax = st.number_input("Vergi (KDV) Oranı %", min_value=0.0, max_value=100.0,
                                  value=float(S["tax_rate"] or 0), step=1.0)
            alert = st.toggle("Stok uyarısı (bildirimlerde kritik stokları göster)", value=S["stock_alert"] == "1")
            near = st.number_input("'Minimuma yakın' eşiği (minimumun % kaç üstü)", min_value=0.0, max_value=500.0,
                                   value=float(S["near_min_pct"] or 20), step=5.0)
            auto = st.toggle("Otomatik yedekleme (günde bir kez, uygulama açılışında)", value=S["auto_backup"] == "1")
            keep = st.number_input("Saklanacak yedek sayısı", min_value=1, max_value=100,
                                   value=int(S["backup_keep"] or 10), step=1)
            if st.form_submit_button("Kaydet", type="primary"):
                db.set_settings({"currency": cur, "tax_rate": tax, "stock_alert": "1" if alert else "0",
                                 "near_min_pct": near, "auto_backup": "1" if auto else "0", "backup_keep": keep})
                flash("Sistem ayarları kaydedildi.")
                st.rerun()

    l2, r2 = st.columns([1.5, 1])
    with l2.container(key="card_set_targets"):
        card_title("Rapor Hedefleri")
        with st.form("target_form", border=False):
            c1, c2, c3 = st.columns(3)
            t1 = c1.number_input("Aylık satış hedefi", min_value=0.0, value=float(S["sales_target"] or 0), step=10000.0)
            t2 = c2.number_input("Aylık üretim kapasitesi (saat)", min_value=0.0,
                                 value=float(S["capacity_hours"] or 0), step=10.0)
            t3 = c3.number_input("Hedef stok devir (x)", min_value=0.0, value=float(S["turnover_target"] or 0), step=0.5)
            if st.form_submit_button("Kaydet", type="primary"):
                db.set_settings({"sales_target": t1, "capacity_hours": t2, "turnover_target": t3})
                flash("Hedefler kaydedildi.")
                st.rerun()

    with r2.container(key="card_set_backup"):
        card_title("Yedekleme")
        b1, b2 = st.columns(2)
        if b1.button("💾 Şimdi Yedekle", width="stretch"):
            p = db.backup_now("manuel")
            flash(f"Yedek alındı: {p.name}")
            st.rerun()
        if db.DB_PATH.exists():
            b2.download_button("⬇ Veritabanını İndir", data=db.DB_PATH.read_bytes(), width="stretch",
                               file_name=f"erp_{datetime.now():%Y%m%d_%H%M}.db", mime="application/octet-stream")
        backups = db.list_backups()
        if backups:
            chosen = st.selectbox("Yedekler", backups, format_func=lambda p: p.name, key="bk_sel")
            c1, c2 = st.columns(2)
            c1.download_button("⬇ Yedeği İndir", data=chosen.read_bytes(), file_name=chosen.name,
                               width="stretch", mime="application/octet-stream", key="bk_dl")
            if c2.button("↺ Bu Yedeğe Dön", width="stretch", key="bk_restore"):
                st.session_state["_confirm_restore"] = str(chosen)
            if st.session_state.get("_confirm_restore") == str(chosen):
                st.warning("Mevcut veriler bu yedekle değiştirilecek (önce otomatik yedek alınır). Emin misiniz?")
                y, n = st.columns(2)
                if y.button("Evet, geri yükle", type="primary", width="stretch"):
                    db.restore_backup(chosen)
                    st.session_state.pop("_confirm_restore", None)
                    flash("Yedek geri yüklendi.")
                    st.rerun()
                if n.button("Vazgeç", width="stretch", key="bk_cancel"):
                    st.session_state.pop("_confirm_restore", None)
                    st.rerun()
        else:
            st.caption("Henüz yedek yok.")
        up = st.file_uploader("Dosyadan geri yükle (.db)", type=["db"], key="bk_upload")
        if up is not None and st.button("Yüklenen dosyayı geri yükle", key="bk_up_btn"):
            try:
                db.restore_from_bytes(up.getvalue())
                flash("Veritabanı dosyadan geri yüklendi.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))

    with st.container(key="card_set_danger"):
        card_title("Tehlikeli Bölge")
        st.caption("Tüm ürün, stok, müşteri, satış, sipariş ve gelir/gider kayıtlarını siler. Ayarlar korunur; "
                   "silmeden önce otomatik yedek alınır.")
        ok = st.checkbox("Tüm verilerin silineceğini anlıyorum", key="reset_ok")

        def _reset():
            db.reset_all_data()
            st.session_state["reset_ok"] = False
            st.session_state.pop("selected_product", None)
            flash("Tüm veriler silindi.", "🗑")

        st.button("Tüm Verileri Sil", disabled=not ok, key="reset_btn", on_click=_reset)
