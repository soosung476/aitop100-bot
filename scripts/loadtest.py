# 동시 접속 시험: 가상 사용자 여러 명이 '한꺼번에' 메시지를 하나씩 보낼 때, 마지막 사람이 답을 받기까지 몇 초 걸리는지 잰다 (서버에서 실행)
# 사용법:
#   1명, 6명, 12명, 24명, 48명 차례로:   .venv/bin/python scripts/loadtest.py
#   원하는 인원만:                       .venv/bin/python scripts/loadtest.py 6 12
# 카카오 웹훅·콜백만 빼고, 실제 봇과 같은 길(main.run_with_lock + 4분 제한)로 에이전트를 부른다
# 답변 전체는 state/load_logs/ 폴더에 파일로 남는다
# ⚠️ 대회 당일 운영진 액션 서버에 붙여서 돌리지 않는다('자동화 대량 요청') → 가짜 서버로만 돌린다
import argparse
import asyncio
import contextvars
import logging
import os
import re
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import action_api
import agent
import main

BASE_DIR = Path(__file__).resolve().parent.parent
RUN_STAMP = datetime.now().strftime("%Y%m%d%H%M%S")

# 도구를 불러야 답할 수 있는 질문들 (조회만 하고 주문은 넣지 않는다)
QUESTIONS = [
    "사과(부사) 10kg 지금 재고 있어요? 가격도 알려 주세요.",
    "남궁민이고 연락처는 010-5050-6060이에요. 제 회원 등급이 뭐예요?",
    "지금 주문할 수 있는 활어 뭐 있어요?",
    "고구마(밤) 3상자랑 배(신고) 2상자 시키면 배송비 포함해서 얼마예요?",
    "생굴은 언제부터 주문할 수 있어요?",
    "다음 주 금요일에 받으려면 언제까지 주문해야 해요?",
]

# main.reply와 agent.run_agent가 실패했을 때 보내는 안내 문구의 앞부분
FAILED_ANSWERS = ("지금 답변이 어려워요", "답변 준비가 너무 오래 걸렸어요", "처리 과정이 길어져")

# ContextVar: 동시에 도는 작업마다 따로 갖는 변수. 메시지마다 LLM 호출 수와 줄 선 시간을 따로 모은다
current = contextvars.ContextVar("current")


async def measured_ask_llm(**kwargs):
    # agent.ask_llm과 똑같이 문지기(llm_slots)를 거치되, 자리가 날 때까지 기다린 시간을 잰다
    stat = current.get()
    started = time.monotonic()
    async with agent.llm_slots:
        stat["wait"] += time.monotonic() - started
        stat["calls"] += 1
        return await agent.llm.chat.completions.create(**kwargs)


agent.ask_llm = measured_ask_llm


class HttpCounter(logging.Handler):
    # openai 패키지가 남기는 로그를 세어서 Hive가 429(요청이 너무 많음)를 몇 번 돌려줬는지, 재시도를 몇 번 했는지 센다
    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.status = {}
        self.retries = 0

    def emit(self, record):
        message = record.getMessage()
        if "Retrying request" in message:
            self.retries += 1
        found = re.search(r'"HTTP/[\d.]+ (\d{3})', message)
        if found and "chat/completions" in message:
            code = found.group(1)
            self.status[code] = self.status.get(code, 0) + 1


counter = HttpCounter()
# 서버에 깔린 openai 패키지는 요청 로그를 "httpx"가 아니라 "httpx2"라는 이름으로 남긴다 (둘 다 붙여 둔다)
for name in ("httpx", "httpx2", "openai"):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.addHandler(counter)
    logger.propagate = False  # 요청마다 찍히는 로그가 화면을 덮지 않게 한다
logging.getLogger("bot").setLevel(logging.WARNING)


async def one_user(wave, no):
    stat = {"wait": 0.0, "calls": 0}
    current.set(stat)
    user_key = f"load:{RUN_STAMP}:{wave}:{no}"
    text = QUESTIONS[no % len(QUESTIONS)]
    started = time.monotonic()
    # main.reply와 같은 처리 (카카오 콜백만 뺐다)
    try:
        answer = await asyncio.wait_for(main.run_with_lock(user_key, text), timeout=main.AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        answer = "답변 준비가 너무 오래 걸렸어요. (4분 초과)"
    except Exception as e:
        answer = f"지금 답변이 어려워요. ({e})"
    stat["seconds"] = time.monotonic() - started
    stat["ok"] = not answer.startswith(FAILED_ANSWERS)
    stat["question"] = text
    stat["answer"] = answer
    return stat


async def run_wave(size, log_file):
    counter.reset()
    started = time.monotonic()
    # gather: 모든 사용자의 대화를 한꺼번에 시작하고 전부 끝날 때까지 기다린다
    results = await asyncio.gather(*(one_user(size, no) for no in range(size)))
    total = time.monotonic() - started

    seconds = sorted(r["seconds"] for r in results)
    ok = sum(r["ok"] for r in results)
    calls = sum(r["calls"] for r in results)
    max_wait = max(r["wait"] for r in results)
    too_many = counter.status.get("429", 0)
    print(
        f"{size:>4}명 | 성공 {ok:>2}/{size:<2} | 가장 빠름 {seconds[0]:5.1f}초 | 중간 {statistics.median(seconds):5.1f}초 | "
        f"가장 늦음 {seconds[-1]:5.1f}초 | 줄 선 시간 최대 {max_wait:5.1f}초 | LLM 호출 {calls:>3}번 | "
        f"429 {too_many}번 | 재시도 {counter.retries}번",
        flush=True,
    )

    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"\n===== {size}명 (전체 {total:.1f}초, HTTP 상태 {counter.status}) =====\n")
        for no, r in enumerate(results):
            f.write(f"\n[{no}] {r['seconds']:.1f}초, LLM {r['calls']}번, 줄 {r['wait']:.1f}초, {'성공' if r['ok'] else '실패'}\n")
            f.write(f"Q: {r['question']}\nA: {r['answer']}\n")


async def run(sizes):
    log_dir = BASE_DIR / "state" / "load_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{RUN_STAMP}.txt"

    print(f"지시문: {agent.PROMPT_FILE.relative_to(BASE_DIR)}")
    print(f"액션 서버: {action_api.BASE_URL or '(연결 안 함)'}")
    print(f"동시에 부르는 LLM 수(문지기 자리): {os.getenv('LLM_CONCURRENCY', '4')}  /  답변 제한 시간: {main.AGENT_TIMEOUT}초")
    print()
    for size in sizes:
        await run_wave(size, log_file)
        await asyncio.sleep(3)  # 앞 묶음의 요청이 Hive에서 완전히 빠지도록 잠깐 쉰다
    print(f"\n답변 전체: {log_file.relative_to(BASE_DIR)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="동시 접속 시험")
    parser.add_argument("sizes", nargs="*", type=int, default=[1, 6, 12, 24, 48], help="한꺼번에 보내는 사용자 수")
    asyncio.run(run(parser.parse_args().sizes))
