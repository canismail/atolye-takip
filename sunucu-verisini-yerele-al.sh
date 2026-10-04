#!/bin/bash
# Sunucudaki (mobil ile ortak) veriyi bu bilgisayardaki YEREL veritabanına kopyalar.
# Yerel mod verisinin eskisi data/backups/ altına yedeklenir; sunucuya hiçbir şey yazılmaz.
# Çalıştır:  bash sunucu-verisini-yerele-al.sh
cd "$(dirname "$0")" || exit 1
PY=./.venv/bin/python; [ -x "$PY" ] || PY=python3
TMP="$(mktemp -t sunucu_al).py"
cat > "$TMP" <<'PYEOF'
import getpass, shutil, sqlite3, sys, time
from pathlib import Path
from core import db, remote

if not remote.available():
    sys.exit("server.txt bulunamadı: sunucu adresi tanımlı değil.")
print("Sunucu:", remote.server_url())
user = input("Kullanıcı adı: ").strip()
remote.login(user, getpass.getpass("Şifre: "))
data = remote.call("backup", "exportAll")
snap = db._build_snapshot(data["tables"])
db._seed_machines(snap)          # makineler (yerel tablo) kurulumdaki 4 makineyle başlar
snap.commit()

dst_path = db.DB_PATH
db.DATA_DIR.mkdir(parents=True, exist_ok=True)
if dst_path.exists():
    bk = db.DATA_DIR / "backups"
    bk.mkdir(exist_ok=True)
    keep = bk / f"erp_yerel_oncesi_{time.strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(dst_path, keep)
    print("Eski yerel veri yedeklendi:", keep.name)
    dst_path.unlink()
dst = sqlite3.connect(dst_path)
snap.backup(dst)
dst.close()

# Fotoğraflar: sunucudan indirilmiş önbellek varsa yerel klasöre kopyala (var olanların üzerine yazmaz)
src, tgt = db.DATA_DIR / "image_cache", db.DATA_DIR / "images"
n = 0
if src.is_dir():
    tgt.mkdir(exist_ok=True)
    for f in src.iterdir():
        if f.is_file() and not (tgt / f.name).exists():
            shutil.copy2(f, tgt / f.name); n += 1
cnt = {t: snap.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("products", "stock_items", "work_orders", "customers")}
print("Tamam. Yerel veri:", cnt, f"· {n} fotoğraf kopyalandı")
print("Panel yerel moddaysa (Profil menüsü → 💻 Yerel) sayfayı yenileyin.")
PYEOF
PYTHONPATH="$PWD" "$PY" "$TMP"
rm -f "$TMP"
