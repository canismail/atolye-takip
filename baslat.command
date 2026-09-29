#!/bin/bash
# Çift tıklayarak başlat (macOS)
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "İlk kurulum yapılıyor..."
  python3 -m venv .venv
  ./.venv/bin/pip install --upgrade pip
  ./.venv/bin/pip install -r requirements.txt
fi
./.venv/bin/streamlit run app.py
