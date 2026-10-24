#!/bin/bash
# 리허설 모드 켜기·끄기 (맥에서 실행)
#   ./scripts/rehearsal.sh on      가짜 액션 서버를 켜고, 봇이 그 서버를 '운영진 액션 서버'로 쓰게 한다
#   ./scripts/rehearsal.sh off     원래대로 되돌린다 (가짜 서버 끄기, .env에서 리허설 줄 지우기)
#   ./scripts/rehearsal.sh status  지금 상태 보기
# 서버 .env에 BEGIN~END 표시 사이의 줄만 넣고 지우므로 다른 설정(토큰, 키)은 건드리지 않는다
set -e
KEY="$HOME/.ssh/aitop100_gabia"
SERVER="ubuntu@1.201.111.145"
MODE="$1"

if [[ "$MODE" != "on" && "$MODE" != "off" && "$MODE" != "status" ]]; then
  echo "사용법: $0 on | off | status"
  exit 1
fi

ssh -i "$KEY" "$SERVER" "MODE=$MODE bash -s" <<'REMOTE'
set -e
cd ~/aitop100-bot

remove_block() {
  sed -i '/^# >>> REHEARSAL BEGIN$/,/^# <<< REHEARSAL END$/d' .env
  chmod 600 .env
}

if [ "$MODE" = "on" ]; then
  # 가짜 액션 서버 켜기 (서버 안에서만 접속 가능한 127.0.0.1:9000, 죽으면 다시 켜짐)
  sudo systemctl stop aitop100-mock 2>/dev/null || true
  sudo systemd-run --quiet --unit=aitop100-mock --collect -p Restart=always -p User=ubuntu \
    -p WorkingDirectory=$PWD .venv/bin/uvicorn --app-dir examples/action_server mock_server:app --host 127.0.0.1 --port 9000
  # 봇이 가짜 서버를 쓰도록 .env에 줄 추가 (두 번 켜도 한 번만 들어가게 먼저 지운다)
  remove_block
  cat >> .env <<'ENV'
# >>> REHEARSAL BEGIN
ACTION_API_BASE_URL=http://127.0.0.1:9000
ACTION_API_HEADER_NAME=X-API-Key
ACTION_API_HEADER_VALUE=practice-key
ACTION_API_USER_HEADER=X-User-Key
# <<< REHEARSAL END
ENV
  sudo systemctl restart aitop100-bot
elif [ "$MODE" = "off" ]; then
  remove_block
  sudo systemctl stop aitop100-mock 2>/dev/null || true
  sudo systemctl restart aitop100-bot
fi

sleep 3
echo "봇: $(systemctl is-active aitop100-bot)"
echo "가짜 액션 서버: $(systemctl is-active aitop100-mock 2>/dev/null || true)"
if grep -q '^# >>> REHEARSAL BEGIN$' .env; then echo ".env: 리허설 모드 (액션 서버 = 가짜 서버)"; else echo ".env: 보통 모드"; fi
curl -s -m 5 http://127.0.0.1:8000/health; echo
REMOTE
