#!/usr/bin/env bash
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -d .venv ]; then
  echo "처음 실행: 실행 환경을 준비합니다..."
  $PY -m venv .venv || { echo "Python 3.10 이상이 필요합니다"; exit 1; }
fi
. .venv/bin/activate
python -m pip install -q --disable-pip-version-check -r requirements.txt
python -m pip install -q --disable-pip-version-check -r requirements-vision.txt 2>/dev/null || echo "사물 인식 부품은 설치하지 못했습니다(사진 제보는 설명 낱말·AI 판독으로 동작)"
python run.py "$@"
