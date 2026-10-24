#!/bin/bash
# 맥 터미널에서 직접 실행: 봇 인증 토큰만 입력받아 서버 .env의 BOT_TOKEN을 바꾼다
# (웹훅 헤더 값은 건드리지 않는다. 처음 실행이라 .env가 없으면 헤더 값을 새로 만들어 보여 준다)
set -e
KEY="$HOME/.ssh/aitop100_gabia"
SERVER="ubuntu@1.201.111.145"

read -r -s -p "봇 인증 토큰(BOT_TOKEN)을 붙여넣고 Enter: " BOT_TOKEN
echo
# 앞뒤 공백 제거
BOT_TOKEN=$(printf %s "$BOT_TOKEN" | tr -d '[:space:]')
if ! [[ "$BOT_TOKEN" =~ ^[0-9a-f]{32}$ ]]; then
  echo "⚠️  입력한 값이 32자리 16진수가 아니에요(길이 ${#BOT_TOKEN}). 봇 화면 [인증 토큰]의 [복사] 버튼으로 다시 복사해 보세요."
  read -r -p "그래도 저장할까요? (y/N) " yn
  [[ "$yn" == "y" ]] || exit 1
fi

printf '%s\n' "$BOT_TOKEN" | ssh -i "$KEY" "$SERVER" '
set -e
cd ~/aitop100-bot
umask 077
read -r t
touch .env
grep -v "^BOT_TOKEN=" .env > .env.tmp || true
echo "BOT_TOKEN=$t" >> .env.tmp
if ! grep -q "^WEBHOOK_HEADER_VALUE=" .env.tmp; then
  v=$(openssl rand -hex 24)
  echo "WEBHOOK_HEADER_NAME=X-Bot-Secret" >> .env.tmp
  echo "WEBHOOK_HEADER_VALUE=$v" >> .env.tmp
  echo "새 웹훅 헤더 — 이름: X-Bot-Secret / 값: $v (카카오 웹훅 설정에 넣으세요)"
fi
mv .env.tmp .env
sudo systemctl restart aitop100-bot
echo "BOT_TOKEN 저장 + 서버 재시작 완료"
'
