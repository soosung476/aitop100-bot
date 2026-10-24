#!/bin/bash
# 맥에서 실행: 코드를 서버로 올리고 FastAPI를 다시 시작한다
# (.env, .venv, state(대화 기억 DB)는 서버 것을 그대로 둔다)
set -e
KEY="$HOME/.ssh/aitop100_gabia"
SERVER="ubuntu@1.201.111.145"

cd "$(dirname "$0")"
rsync -az -e "ssh -i $KEY" \
  --exclude .venv --exclude .env --exclude .git --exclude state \
  --exclude __pycache__ --exclude .DS_Store \
  ./ "$SERVER:/home/ubuntu/aitop100-bot/"
ssh -i "$KEY" "$SERVER" 'cd ~/aitop100-bot && .venv/bin/pip install -q -r requirements.txt && sudo systemctl restart aitop100-bot && sleep 2 && systemctl is-active aitop100-bot'
curl -s https://bot.soosungcloud.com/health
echo
