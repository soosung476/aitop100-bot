import asyncio
import logging
import os
from collections import defaultdict, deque

import httpx
from fastapi import BackgroundTasks, FastAPI, Request, Response

import agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

# 봇 인증 토큰: 카카오디벨로퍼스 > [카카오톡 봇] > [봇]에서 확인, 서버의 .env 파일에 넣는다
# 붙여넣을 때 섞여 들어간 앞뒤 공백·따옴표·"KakaoAK " 접두어는 떼어 낸다
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip().strip("\"'").strip().removeprefix("KakaoAK ").strip()
# 웹훅 커스텀 헤더(선택): 카카오 웹훅 설정에 등록한 이름·값과 같아야 요청을 받아 준다
WEBHOOK_HEADER_NAME = os.getenv("WEBHOOK_HEADER_NAME", "")
WEBHOOK_HEADER_VALUE = os.getenv("WEBHOOK_HEADER_VALUE", "")

KAKAO_CALLBACK_URL = "https://kapi.kakao.com/v1/bot/callback"

# 콜백 토큰은 5분 안에 써야 하므로, 에이전트는 4분 안에 끝내고 못 끝내면 안내 문구를 보낸다
AGENT_TIMEOUT = 240
# 카카오 말풍선 제한: 하나에 최대 1,000자, 한 번에 최대 3개
BUBBLE_LIMIT = 1000
MAX_BUBBLES = 3

# 봇이 채팅방에 초대됐을 때(ENTRANCE) 보내는 인사
GREETING = "안녕하세요! 교동마을·갯마을 공동 주문 상담봇이에요. 주문하고 싶은 상품을 말씀해 주세요."

app = FastAPI()

# 같은 사용자의 메시지는 한 번에 하나씩 처리한다 (연달아 보내도 대화 기억이 꼬이지 않게)
user_locks = defaultdict(asyncio.Lock)
# 최근에 처리한 메시지 번호 (카카오가 같은 이벤트를 다시 보내도 두 번 답하지 않게)
seen_message_ids = deque(maxlen=1000)


# 서버가 살아 있는지 확인하는 주소
@app.get("/health")
def health():
    return {"status": "ok"}


# 카카오톡 서버가 사용자 메시지를 보내 주는 주소
# 1초 안에 204로 먼저 답하고, 실제 답장은 BackgroundTasks(응답을 보낸 뒤 실행되는 작업)로 콜백 API에 보낸다
@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    if WEBHOOK_HEADER_NAME and request.headers.get(WEBHOOK_HEADER_NAME) != WEBHOOK_HEADER_VALUE:
        log.warning("커스텀 헤더 불일치 — 무시")
        return Response(status_code=204)

    payload = await request.json()
    event_type = payload.get("t")
    data = payload.get("d", {})
    callback_token = data.get("callbackToken", "")

    if event_type == "MESSAGE_CREATE" and callback_token:
        message_id = data.get("id")
        if message_id is not None and message_id in seen_message_ids:
            log.info("이미 처리한 메시지라 건너뜀 id=%s", message_id)
            return Response(status_code=204)
        seen_message_ids.append(message_id)

        # 대화 상대 구분값: 채팅방 + 발화자 (같은 사람이라도 채팅방이 다르면 대화를 따로 기억한다)
        user_key = f"{data.get('botGroupKey', '')}:{data.get('botUserKey', '')}"
        content = data.get("content", "")
        log.info("MESSAGE_CREATE user=%s content=%s", user_key[-12:], content[:100])
        background_tasks.add_task(reply, callback_token, user_key, content)

    elif event_type == "ENTRANCE" and callback_token:
        background_tasks.add_task(send_callback, callback_token, GREETING)

    return Response(status_code=204)


async def run_with_lock(user_key, text):
    async with user_locks[user_key]:
        return await agent.run_agent(user_key, text)


# 답장 만들기: 에이전트에게 답을 받아 카카오로 보낸다
# 에이전트가 실패하거나 너무 오래 걸려도 사용자에게는 꼭 답장이 가도록 한다
async def reply(callback_token: str, user_key: str, text: str):
    try:
        answer = await asyncio.wait_for(run_with_lock(user_key, text), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        log.error("에이전트 시간 초과 user=%s", user_key[-12:])
        answer = "답변 준비가 너무 오래 걸렸어요. 잠시 후 다시 말씀해 주세요."
    except Exception as e:
        log.error("에이전트 실패: %s", e)
        answer = "지금 답변이 어려워요. 잠시 후 다시 시도해 주세요."
    log.info("ANSWER user=%s %s", user_key[-12:], answer[:300].replace("\n", " "))
    await send_callback(callback_token, answer)


def clean_text(text):
    # 카카오톡은 마크다운을 꾸밈으로 바꿔 주지 않으므로 자주 섞이는 기호를 지운다
    lines = []
    for line in text.strip().split("\n"):
        if line.strip().startswith("```"):  # 코드 블록 표시 줄(```, ```json)은 뺀다
            continue
        if line.lstrip().startswith("#"):  # 제목 기호(#)는 떼어 낸다
            line = line.lstrip().lstrip("#").strip()
        lines.append(line)
    return "\n".join(lines).replace("**", "")


def split_bubbles(text):
    # 말풍선 하나에 BUBBLE_LIMIT자까지 담고, 넘치면 줄 단위로 나눈다
    bubbles = []
    current = ""
    for line in text.split("\n"):
        while len(line) > BUBBLE_LIMIT:  # 한 줄이 제한보다 길면 제한 길이로 자른다
            if current:
                bubbles.append(current)
                current = ""
            bubbles.append(line[:BUBBLE_LIMIT])
            line = line[BUBBLE_LIMIT:]
        if not current:
            current = line
        elif len(current) + 1 + len(line) <= BUBBLE_LIMIT:
            current += "\n" + line
        else:
            bubbles.append(current)
            current = line
    bubbles.append(current)
    bubbles = [b.strip() for b in bubbles if b.strip()]

    # 말풍선이 MAX_BUBBLES개를 넘으면 뒷부분은 생략한다
    if len(bubbles) > MAX_BUBBLES:
        notice = "\n(답변이 길어 뒷부분은 생략했어요)"
        bubbles = bubbles[:MAX_BUBBLES]
        bubbles[-1] = bubbles[-1][: BUBBLE_LIMIT - len(notice)] + notice
    return bubbles or ["답변을 만들지 못했어요. 다시 한 번 말씀해 주세요."]


# 카카오 메시지 콜백 API로 답장 보내기 (콜백 토큰은 5분 안에 써야 한다)
async def send_callback(callback_token: str, answer: str):
    if not BOT_TOKEN:
        log.error("BOT_TOKEN이 없어 답장을 못 보냄 — 서버 .env 확인")
        return
    outputs = [{"simpleText": {"text": bubble}} for bubble in split_bubbles(clean_text(answer))]
    body = {
        "skillResponse": {
            "version": "2.0",
            "template": {"outputs": outputs},
        }
    }
    headers = {
        "Authorization": f"KakaoAK {BOT_TOKEN}",
        "X-Bot-Callback-Token": callback_token,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(KAKAO_CALLBACK_URL, json=body, headers=headers)
    if resp.status_code != 200:
        log.error("callback 실패 %d %s", resp.status_code, resp.text)
