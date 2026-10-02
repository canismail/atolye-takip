# Atölye Yönetim Paneli (ERP-AI)

`test.html` tasarımının Streamlit ile çalışan hâli. Veriler `data/erp.db` (SQLite) dosyasında tutulur, ilk açılışta veritabanı boştur.

## Kurulum ve çalıştırma

```bash
cd ~/Desktop/ERP-AI
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Tarayıcıda http://localhost:8501 açılır. Kurulumdan sonra `baslat.command` dosyasına çift tıklayarak da başlatabilirsin (ilk seferde sanal ortamı kendisi kurar).

> Streamlit 1.50 veya üstü gerekir (`st.dialog`, tablo satır seçimi, `width="stretch"`).

## Önerilen başlangıç sırası

1. **Ayarlar**: Firma bilgileri, KDV oranı, hedefler.
2. **Malzeme Bileşenleri**: Ürünlerde kullanılacak hammadde/sarf/yedek parçaları tek tek tanımla (kategori, birim, minimum stok, birim maliyet, konum). Kod adından otomatik oluşur.
3. **Stok**: Tanımladığın bileşenlerin gerçek stok miktarlarını "± Stok Hareketi" ile gir (giriş/çıkış/sayım).
4. **Ürünler**: Ürünü ekle, ardından alttaki sekmelerden **malzeme bileşenleri** (Malzeme Bileşenleri sayfasındaki kalemlerden seçilir) ve **operasyonlar** (süre) gir.
5. **Müşteriler**
6. **Satışlar** ve **Siparişler**
7. **Gelir / Gider**: Kira, personel, malzeme alımı gibi manuel hareketler.

## Kod üretimi

Ürün, malzeme bileşeni ve müşteri kodları **elle girilmez** — isimden otomatik oluşturulur (adın ilk kelimesi + sıra no, örn. "Masa Ayağı" → `MASA-01`, aynı kökten ikinci kayıt `MASA-02` olur). Kod, kayıt oluşturulunca sabitlenir; sonradan isim değiştirilse bile kod değişmez.

## Sayfalar ve işlevler

| Sayfa | Neler çalışıyor |
|---|---|
| Dashboard | KPI'lar (geçen aya göre değişim), yıllık aylık satış grafiği, son işlemler, kritik stoklar, bekleyen siparişler, cari özet (alacak, vadesi geçen, tahsilat oranı). "Tümünü Gör" butonları ilgili sayfaya gider. |
| Siparişler | Ekle, düzenle, sil. İlerleme güncelleme (durum otomatik: Bekliyor, Üretimde, Tamamlandı), tamamla, iptal et, yeniden aç. Termin gecikmesi, tahmini süre, reçeteye göre malzeme ihtiyacı ve stok yeterliliği. |
| Üretim Planı | Ürünlerin operasyon süresine + buffer (%) eklenerek günlük/haftalık üretilebilecek adet. Varsayımlar (günlük saat, çalışan sayısı, çalışma günleri, buffer) sayfada düzenlenir. Üretim hesaplayıcı: N adet için gereken süre, iş günü ve bitiş tarihi (gün gün). Açık siparişler termin sırasıyla bugünden başlayarak planlanır, terminden geç biten "Gecikir" görünür. |
| Ürünler | Ekle, düzenle, sil (satış veya sipariş varsa engellenir). Tablodan seçilen ürünün detayı: malzeme bileşenleri ve operasyonlarda ekle, düzenle, sil, sırala (▲▼). Siparişler sekmesinden doğrudan sipariş açılır. Malzeme maliyeti ve toplam süre otomatik hesaplanır. |
| Malzeme Bileşenleri | Ürünlerin alt bileşenlerini (hammadde, sarf, yedek parça vb.) tanımla: kategori, birim, minimum stok, birim maliyet, konum. Ekle, düzenle, sil (reçetede kullanılıyorsa engellenir). Miktar burada girilmez — "□ Stok Hareketi" ile Stok sayfasına yönlendirir. |
| Stok | Malzeme Bileşenleri'nde tanımlanan kalemlerin mevcut miktar/değer/durumunu gösterir. Stok giriş, çıkış ve sayım düzeltmesi, hareket geçmişi. Durum otomatik hesaplanır: Normal, Minimuma Yakın, Kritik. Yeni bileşen tanımlama ve detay düzenleme Malzeme Bileşenleri sayfasına yönlendirir. |
| Müşteriler | Ekle, düzenle, sil, aktif/pasif yap. Toplam satış, açık bakiye, vadesi geçen tutar ve satış geçmişi. |
| Satışlar | Ekle (KDV hesabı, iskonto için elle tutar), düzenle, sil, tahsil et, tahsilatı geri al. Durum ve dönem filtresi, vadesi geçenler. |
| Gelir / Gider | Ekle, düzenle, sil. Dönem, tür ve arama filtresi. KPI'lar: gelir, gider, net, kâr marjı. |
| Raporlar | Aylık satış (hedefe göre), üretim saati (kapasiteye göre), stok devir hızı. En çok satan ürünler, aylık özet, gelir/gider trendi. Tek tablo veya tüm rapor Excel'e aktarılabilir. |
| Ayarlar | Firma ve kullanıcı bilgileri, para birimi, KDV, stok uyarısı, minimuma yakın eşiği, otomatik yedekleme, rapor hedefleri. Manuel yedek, yedek indirme, geri yükleme, tüm verileri silme. |

**Fotoğraf:** Ürün ve malzeme bileşeni formlarında fotoğraf yüklenebilir (PNG/JPG/WEBP). Görseller küçültülüp `data/images/` klasörüne kaydedilir; tablolarda küçük önizleme, detay kartında büyük görsel görünür. Stok satırındaki ürünler kendi fotoğrafını kullanır. Fotoğraflar veritabanı yedeğine dahil değildir, yedek alırken `data/images/` klasörünü de kopyalayın.

**Üst bar:** Arama kutusu açık sayfadaki tüm tablolarda arar. 🔔 kritik stok, vadesi geçen alacak ve termini geçen siparişleri listeler. Profil menüsünden Ayarlar'a gidilir.

**Dışa aktarma:** Her sayfadaki tablonun altında **"⬇ PDF olarak indir"** düğmesi vardır; o an ekranda görünen (arama/filtre uygulanmış) veriyi PDF olarak indirir. Raporlar sayfasındaki tablolar ayrıca Excel'e de aktarılabilir.

## Otomatik bağlantılar

- "Ödendi" durumundaki satış, Gelir / Gider'e **otomatik gelir kaydı** yazar. Tutar veya tarih değişirse kayıt güncellenir. Tahsilat geri alınırsa veya satış silinirse kayıt da kaldırılır.
- Sipariş tamamlandığında stoktan malzeme **düşülmez**. Stok hareketleri Stok sayfasından elle yapılır.

## Klasör yapısı

```
app.py              # giriş noktası: sidebar, üst bar, sayfa yönlendirme
core/db.py          # SQLite şema, CRUD, satış→gelir senkronu, kod üretimi, yedekleme
core/metrics.py     # KPI ve rapor hesapları
core/ui.py          # tasarım CSS'i, KPI kartları, tablo, PDF export, silme onayı
core/pdf_export.py  # tablo → PDF üretimi
core/planning.py    # üretim planı hesapları (kapasite, iş takvimi)
core/utils.py       # para/tarih biçimlendirme, Türkçe→ASCII
core/assets/        # yazı tipleri (PDF), logo/favicon
views/*.py          # her sayfa ayrı dosya (materials.py = Malzeme Bileşenleri)
data/erp.db         # veritabanı (ilk çalıştırmada oluşur)
data/backups/       # yedekler
```

## Merkezi veritabanı (telefonla ortak)

`server.txt` dosyasında bir sunucu adresi varsa (ya da `ERP_SERVER_URL` ortam değişkeni tanımlıysa) panel yerel `data/erp.db` yerine
mobil uygulamanın kullandığı sunucudaki veriyle çalışır; açılışta kullanıcı adı ve şifre sorulur
(`ERP_USER` / `ERP_PASS` tanımlıysa otomatik girer). Telefonda yapılan değişiklik en geç ~6 sn içinde, panelde yapılan değişiklik anında ortak olur.

- Okumalar sunucudan alınan anlık görüntü üzerinden, yazmalar sunucunun servisleri üzerinden yapılır (`core/remote.py`, `core/db.py`).
- Fotoğraflar sunucuda tutulur; `data/image_cache` yalnızca yerel önbellektir.
- "Şimdi Yedekle" sunucudaki verinin bu bilgisayara `.db` kopyasını kaydeder; sunucu ayrıca her gün kendi yedeğini alır.
- Yerel moda dönmek için `server.txt` dosyasını silin (veya adı değiştirin).
