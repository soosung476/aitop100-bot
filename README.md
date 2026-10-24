# AITOP100 카카오톡 상담봇 (TOPTALK)

카카오톡 채널 TOPTALK ↔ `https://bot.soosungcloud.com/webhook` (가비아 클라우드, FastAPI) ↔ Hive DeepSeek

## 파일 구조

| 파일 | 하는 일 | 대회 당일 |
|---|---|---|
| `prompts/system.md` | 역할, 원칙, 상담 순서, 보안 규칙 (지시문) | **고친다** |
| `data/*.md`, `data/*.txt` | 문서 자료. 지시문 뒤에 `<자료>`로 자동으로 붙는다 | **바꾼다** |
| `data/*.csv` | 표 자료. `search_table` 도구로 찾는다 | **바꾼다** |
| `tools.py` | 도구(함수) 설명과 실행 코드 | 필요하면 추가 |
| `agent.py` | 대화 기억 + 도구 호출 반복 | 거의 안 고침 |
| `memory.py` | 대화 기억·기록 저장 (SQLite, 서버 `state/bot.db`) | 안 고침 |
| `main.py` | 카카오 웹훅 받기, 답장 보내기(말풍선 1,000자 × 최대 3개) | 인사말(`GREETING`)만 |

지금 들어 있는 자료와 지시문은 연습 문제 4번(두 마을 공동 주문 상담)이다.

## 자주 쓰는 명령어 (맥 터미널)

```bash
# 배포: 서버에 올리고 재시작
./deploy.sh

# 서버 로그 실시간 보기 (MESSAGE_CREATE → 도구 → ANSWER 순서로 찍힌다)
ssh -i ~/.ssh/aitop100_gabia ubuntu@1.201.111.145 'journalctl -u aitop100-bot -f'

# 봇 토큰 바꾸기 (웹훅 헤더는 그대로 둔다)
./set-env.sh
```

## 시험 명령어 (서버에서 .env를 읽어 실행)

```bash
# 서버 접속
ssh -i ~/.ssh/aitop100_gabia ubuntu@1.201.111.145
cd ~/aitop100-bot

# LLM 없이 도는 기본 시험
.venv/bin/python tests/test_basic.py

# 카카오 없이 직접 대화해 보기 (도구 호출이 [ ] 안에 보인다)
sudo systemd-run --quiet --wait --pty -p User=ubuntu -p EnvironmentFile=$PWD/.env -p WorkingDirectory=$PWD .venv/bin/python scripts/chat_test.py

# 가상 고객 자동 시험 + 채점 (카드마다 3번씩)
sudo systemd-run --quiet --wait --pipe -p User=ubuntu -p EnvironmentFile=$PWD/.env -p Environment=BOT_DB_PATH=$PWD/state/sim.db -p WorkingDirectory=$PWD .venv/bin/python scripts/simulate.py --repeat 3 --expected tests/정답_문제4.json
```

카카오톡에서 `/초기화`를 보내면 그 대화방의 기억을 지우고 처음부터 시작한다.

## 서버 .env (git에 올리지 않는다)

`BOT_TOKEN`, `WEBHOOK_HEADER_NAME`, `WEBHOOK_HEADER_VALUE`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`
(선택) `LLM_MAX_TOKENS` — 기본 393216 (모델 최대치)
