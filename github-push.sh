#!/bin/bash
# ERP-AI -> https://github.com/canismail/atolye-takip
cd "$(dirname "$0")"
find .git -name '*.lock' -delete 2>/dev/null
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null
git rm -q --cached package.json.bak 2>/dev/null
git add -A
git diff --cached --quiet || git commit -q -m "Yeni: makine bazli uretim plani, makineler sayfasi, surukle-birak cizelge, stok maliyet/net kar, sunucu modu

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LRVec6Am2Z9Cr9LwEXxnCv"
git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/canismail/atolye-takip.git
git branch -M main
if git push -u origin main; then
  echo "✅ GitHub'a gönderildi: https://github.com/canismail/atolye-takip"
else
  echo "❌ Push başarısız. GitHub girişi gerekiyorsa: 'gh auth login' çalıştırıp bu scripti tekrar çalıştırın."
fi
