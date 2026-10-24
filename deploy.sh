#!/bin/bash
# 맥에서 실행: 코드를 서버로 올리고 FastAPI를 다시 시작한다
# (.env로 시작하는 파일, .venv, state(대화 기억 DB)는 서버 것을 그대로 둔다)
# --delete: 맥에서 지운 파일은 서버에서도 지운다 (예: data/의 옛 자료가 서버에 남아 봇이 계속 읽는 일 방지)
set -e
KEY="$HOME/.ssh/aitop100_gabia"
SERVER="ubuntu@1.201.111.145"

cd "$(dirname "$0")"
rsync -az --delete -e "ssh -i $KEY" \
  --exclude .venv --exclude '.env*' --exclude .git --exclude state \
  --exclude __pycache__ --exclude .DS_Store \
  ./ "$SERVER:/home/ubuntu/aitop100-bot/"
ssh -i "$KEY" "$SERVER" 'cd ~/aitop100-bot && .venv/bin/pip install -q -r requirements.txt && sudo systemctl restart aitop100-bot && sleep 2 && systemctl is-active aitop100-bot'
# 맥의 DNS에 예전 정보가 남아 있어도 확인할 수 있게 서버 IP로 직접 접속해서 본다 (--resolve)
curl -s --retry 3 --retry-connrefused --resolve bot.soosungcloud.com:443:1.201.111.145 https://bot.soosungcloud.com/health
echo
