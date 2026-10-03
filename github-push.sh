#!/bin/bash
# ERP-AI -> https://github.com/canismail/atolye-takip
cd "$(dirname "$0")"
find .git -name '*.lock' -delete 2>/dev/null
find .git/objects -name 'tmp_obj_*' -delete 2>/dev/null
git add -A
git diff --cached --quiet || git commit -q -m "Stok degeri: urunlerde satis fiyati uzerinden

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01LRVec6Am2Z9Cr9LwEXxnCv"
if git push -u origin main; then
  echo "✅ GitHub'a gönderildi: https://github.com/canismail/atolye-takip"
else
  echo "❌ Push başarısız. GitHub girişi gerekiyorsa: 'gh auth login' yapıp scripti tekrar çalıştırın."
fi
