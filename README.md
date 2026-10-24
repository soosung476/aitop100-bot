# AITOP100 카카오톡 상담봇 (TOPTALK)

카카오톡 채널 TOPTALK ↔ `https://bot.soosungcloud.com/webhook` (가비아 클라우드, FastAPI) ↔ Hive DeepSeek
제출용 Kakao Developers App ID: **1620897** (TOPTALK)

## 파일 구조

| 파일 | 하는 일 | 대회 당일 |
|---|---|---|
| `prompts/system.md` | 역할, 원칙, 상담 순서, 보안 규칙 (지시문) | **고친다** |
| `data/*.md`, `data/*.txt` | 문서 자료. 지시문 뒤에 `<자료>`로 자동으로 붙는다 (API 문서도 여기에) | **바꾼다** |
| `data/*.csv` | 표 자료. `search_table` 도구로 찾는다 | **바꾼다** |
| `tools.py` | 도구(함수) 설명과 실행 코드 | 필요하면 추가 |
| `action_api.py` | 운영진 액션 서버를 부르는 공통 함수 (`.env`의 `ACTION_API_*`) | 안 고침 |
| `agent.py` | 대화 기억 + 도구 호출 반복 + 입력·출력 방어 | 거의 안 고침 |
| `memory.py` | 대화 기억·기록 저장 (SQLite, 서버 `state/bot.db`) | 안 고침 |
| `main.py` | 카카오 웹훅 받기, 답장 보내기(말풍선 1,000자 × 최대 3개) | 인사말(`GREETING`)만 |
| `examples/action_server/` | 연습용 가짜 액션 서버와 그 서버용 지시문·자료·정답 | 연습용 |
| `docs/디브리프_초안.md` | 제출할 디브리프 초안 | **채운다** |

지금 `prompts/`와 `data/`에 들어 있는 것은 연습 문제 4번(두 마을 공동 주문 상담)이다.
`data/재고표.csv`의 생굴 비고란에는 일부러 숨은 지시(간접 인젝션)를 넣어 두었다.

## 자동으로 해 주는 것

- 30분 동안 말이 없으면 새 대화로 시작 (`SESSION_MINUTES`), 카톡에서 `/초기화`를 보내도 새로 시작
- Hive는 같은 키로 동시에 5개까지만 받아 줘서, LLM 호출을 동시에 4개까지만 하고 나머지는 줄을 세운다 (`LLM_CONCURRENCY`). 429가 나면 최대 6번 다시 시도
- 2,000자가 넘는 메시지는 거절, 지시문 문장이나 도구 이름이 답에 나오면 안내 문구로 바꿔서 보냄
- 같은 메시지가 두 번 와도 한 번만 처리, 4분 안에 못 끝내면 안내 문구로 답장

⚠️ Hermes도 같은 Hive 키를 쓰므로, 심사 기간(10/31 16:00 ~ 11/1 24:00)에는 Hermes를 쓰지 않는다.

## 대회 당일: 운영진 액션 서버 연결 순서

1. 문제 페이지에서 액션 서버 **주소, 인증 방식, API 문서**를 확인한다
2. 서버 `.env`에 추가한다 (`nano ~/aitop100-bot/.env`)
   ```
   ACTION_API_BASE_URL=https://문제페이지에_나온_주소
   ACTION_API_HEADER_NAME=인증_헤더_이름      # 예: Authorization 또는 X-API-Key
   ACTION_API_HEADER_VALUE=인증_헤더_값        # 예: Bearer abc123
   ACTION_API_USER_HEADER=                      # 대화 구분값을 보내라고 하면 그 헤더 이름
   ```
   → 이 값이 있으면 `call_action_api` 도구가 켜지고, 로컬 기록 도구(`save_record`)는 꺼진다
3. API 문서를 `data/액션서버_API.md`로 저장한다 (예시: `examples/action_server/data/액션서버_API.md`)
4. `prompts/system.md`를 문제에 맞게 고친다 (예시: `examples/action_server/system.md`)
5. `./deploy.sh` → `chat_test.py`로 몇 번 대화해 보기 → 카카오톡에서 확인
6. ⚠️ 운영진 액션 서버에 자동 시험(`simulate.py`)을 여러 번 돌리지 않는다 ('자동화 대량 요청'은 부정행위)
7. 제출하기 전에 최종 배포와 카톡 확인을 끝낸다. **제출 뒤에는 배포·재시작·.env 수정 금지**

## 자주 쓰는 명령어 (맥 터미널)

```bash
# 배포: 서버에 올리고 재시작
./deploy.sh

# 서버 로그 실시간 보기 (MESSAGE_CREATE → 도구 → ANSWER 순서로 찍힌다)
ssh -i ~/.ssh/aitop100_gabia ubuntu@1.201.111.145 'journalctl -u aitop100-bot -f'

# 봇 토큰 바꾸기 (웹훅 헤더는 그대로 둔다)
./set-env.sh
```

맥에서 `bot.soosungcloud.com`이 안 열리면 맥(또는 공유기)의 DNS에 도메인 정지 시절 정보가 남아 있는 것이다. 서버 문제가 아니며 카톡 동작에는 영향이 없다. 확인은 `curl --resolve bot.soosungcloud.com:443:1.201.111.145 https://bot.soosungcloud.com/health`로 한다.

## 시험 명령어 (서버에서 .env를 읽어 실행)

```bash
ssh -i ~/.ssh/aitop100_gabia ubuntu@1.201.111.145
cd ~/aitop100-bot
RUN="sudo systemd-run --quiet --wait --pipe -p User=ubuntu -p EnvironmentFile=$PWD/.env -p WorkingDirectory=$PWD -p Environment=BOT_DB_PATH=$PWD/state/sim.db"

# LLM 없이 도는 기본 시험
.venv/bin/python tests/test_basic.py

# 카카오 없이 직접 대화해 보기 (도구 호출이 [ ] 안에 보인다)
sudo systemd-run --quiet --wait --pty -p User=ubuntu -p EnvironmentFile=$PWD/.env -p WorkingDirectory=$PWD .venv/bin/python scripts/chat_test.py

# 가상 고객 자동 시험 + 채점 (카드마다 3번씩)
$RUN .venv/bin/python scripts/simulate.py --repeat 3 --expected tests/정답_문제4.json

# 공격(인젝션) 시험
$RUN .venv/bin/python scripts/simulate.py --repeat 3 --cards-file tests/공격카드.md --expected tests/정답_공격.json
```

### 가짜 액션 서버로 연습

```bash
# 가짜 서버 켜기 (서버 안에서만 접속 가능한 127.0.0.1:9000)
sudo systemd-run --quiet --unit=aitop100-mock --collect -p User=ubuntu -p WorkingDirectory=$PWD .venv/bin/uvicorn --app-dir examples/action_server mock_server:app --host 127.0.0.1 --port 9000

# 액션 서버 모드로 자동 시험
MOCK="-p Environment=BOT_PROMPT_FILE=examples/action_server/system.md -p Environment=BOT_DATA_DIR=examples/action_server/data -p Environment=ACTION_API_BASE_URL=http://127.0.0.1:9000 -p Environment=ACTION_API_HEADER_NAME=X-API-Key -p Environment=ACTION_API_HEADER_VALUE=practice-key -p Environment=ACTION_API_USER_HEADER=X-User-Key"
$RUN $MOCK .venv/bin/python scripts/simulate.py --repeat 3 --expected examples/action_server/정답.json

# 가짜 서버 끄기
sudo systemctl stop aitop100-mock
```

## 서버 .env (git에 올리지 않는다)

필수: `BOT_TOKEN`, `WEBHOOK_HEADER_NAME`, `WEBHOOK_HEADER_VALUE`, `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`
액션 서버: `ACTION_API_BASE_URL`, `ACTION_API_HEADER_NAME`, `ACTION_API_HEADER_VALUE`, `ACTION_API_USER_HEADER`
선택: `LLM_MAX_TOKENS`(기본 393216, 모델 최대치), `LLM_CONCURRENCY`(기본 4), `SESSION_MINUTES`(기본 30)
