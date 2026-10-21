#!/bin/bash
# Analyse Your Music - 폰에서 보기용 실행 스크립트
# 같은 Wi-Fi의 폰 브라우저에서 접속할 수 있게 서버를 열고, 접속 주소(와 가능하면 QR)를 보여 준다.
# Finder에서 더블클릭하거나 터미널에서 ./start_phone.command 로 실행

DIR="$(cd "$(dirname "$0")" && pwd)"
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"

if [ -z "$LAN_IP" ]; then
  echo "⚠️  Wi-Fi 주소를 찾지 못했습니다. 맥이 Wi-Fi(또는 공유기)에 연결돼 있는지 확인해 주세요."
  exit 1
fi

URL="http://$LAN_IP:5173"
echo "📱 폰(같은 Wi-Fi)에서 열 주소: $URL"
echo "   ※ 인증이 없으니 집 같은 믿을 수 있는 Wi-Fi에서만 쓰세요."
if command -v qrencode >/dev/null 2>&1; then
  qrencode -t ANSIUTF8 "$URL"   # brew install qrencode 가 있으면 QR 코드로도 보여 준다
fi
echo ""

exec "$DIR/start.command" --lan
