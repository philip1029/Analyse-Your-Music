#!/bin/bash
# Analyse Your Music - 백엔드 + 프론트엔드 서버를 한 번에 띄우는 스크립트
# Finder에서 더블클릭하거나 터미널에서 ./start.command 로 실행

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# --lan 을 주면 같은 Wi-Fi의 폰/태블릿에서도 접속할 수 있게 서버를 연다 (인증이 없으니 집 Wi-Fi에서만 쓸 것)
HOST="127.0.0.1"
if [ "$1" = "--lan" ]; then
  HOST="0.0.0.0"
fi

if [ ! -f "$DIR/.env" ]; then
  echo "⚠️  .env 파일이 없습니다. .env.example을 복사해서 LASTFM_API_KEY / USERNAME을 채워주세요."
  echo "   (없어도 서버는 켜지지만 Last.fm 연동 기능은 동작하지 않습니다)"
  echo ""
fi

if [ ! -d "$DIR/data" ] || [ -z "$(ls -A "$DIR/data"/*_scrobbles.csv 2>/dev/null)" ]; then
  echo "⚠️  data/ 폴더에 *_scrobbles.csv 파일이 없습니다. 먼저 스크로블 데이터를 받아주세요."
  echo ""
fi

if ! python3 -c "import fastapi" 2>/dev/null; then
  echo "백엔드 의존성 설치 중..."
  pip3 install -r "$DIR/backend/requirements.txt"
fi

if [ ! -d "$DIR/frontend/node_modules" ]; then
  echo "프론트엔드 의존성 설치 중..."
  (cd "$DIR/frontend" && npm install)
fi

cleanup() {
  echo ""
  echo "서버 종료 중..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null
  exit 0
}
trap cleanup INT TERM HUP

echo "백엔드 서버 시작 → http://localhost:8000"
(cd "$DIR/backend" && exec uvicorn app.main:app --reload --host "$HOST" --port 8000) &
BACKEND_PID=$!

echo "프론트엔드 서버 시작 → http://localhost:5173"
(cd "$DIR/frontend" && exec ./node_modules/.bin/vite --host "$HOST" --port 5173) &
FRONTEND_PID=$!

if [ "$HOST" = "0.0.0.0" ]; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  echo ""
  echo "📱 폰에서 접속: http://${LAN_IP:-<이 맥의 IP>}:5173  (같은 Wi-Fi에 연결돼 있어야 합니다)"
fi

sleep 3
open "http://localhost:5173" 2>/dev/null || true

echo ""
echo "두 서버 모두 실행 중입니다. 이 창을 닫거나 Ctrl+C를 누르면 종료됩니다."
wait
