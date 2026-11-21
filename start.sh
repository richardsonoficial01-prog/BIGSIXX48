#!/usr/bin/env sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Instale Python 3.10 ou superior e execute novamente."
  exit 1
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Use Python 3.10 ou superior."'
for program in ffmpeg ffprobe; do
  if ! command -v "$program" >/dev/null 2>&1; then
    echo "Instale FFmpeg (incluindo ffprobe) e deixe os dois comandos no PATH."
    echo "Alternativa: execute docker compose up --build nesta pasta."
    exit 1
  fi
done

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! cmp -s requirements.txt .venv/clipper-requirements.txt; then
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
  cp requirements.txt .venv/clipper-requirements.txt
fi

echo "Abra http://127.0.0.1:${PORT:-${CLIPPER_PORT:-8000}} no navegador."
echo "Mantenha esta janela aberta enquanto usar o app."
exec .venv/bin/python server.py
