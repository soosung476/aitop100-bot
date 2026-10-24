# 카카오 없이 터미널에서 에이전트와 대화해 보는 시험 도구 (서버에서 실행)
# 사용법:
#   직접 입력하며 대화:      .venv/bin/python scripts/chat_test.py
#   정해 둔 말을 차례로 보내기: .venv/bin/python scripts/chat_test.py "사과 주문되나요?" "2박스요"
# 서버에서는 .env를 읽어야 하므로 README의 '시험 명령어'처럼 systemd-run으로 실행한다
import asyncio
import logging
import sys
from pathlib import Path

# scripts 폴더 밖(프로젝트 폴더)에 있는 agent.py, memory.py를 불러올 수 있게 경로를 추가한다
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import memory

# 도구 호출 기록을 [ ] 안에 보여 준다
logging.basicConfig(level=logging.INFO, format="  [%(message)s]")
logging.getLogger("httpx").setLevel(logging.WARNING)

USER_KEY = "test:chat"


async def main():
    memory.clear_history(USER_KEY)
    messages = sys.argv[1:]

    if messages:
        for text in messages:
            print(f"\n나: {text}")
            print(f"봇: {await agent.run_agent(USER_KEY, text)}")
    else:
        print("대화를 시작합니다. 끝내려면 아무것도 입력하지 않고 Enter")
        while True:
            text = input("\n나: ").strip()
            if not text:
                break
            print(f"봇: {await agent.run_agent(USER_KEY, text)}")

    records = memory.list_records(USER_KEY)
    if records:
        print("\n저장된 기록:")
        for record in records:
            print(f"  #{record['기록번호']} {record['종류']}: {record['내용']}")


asyncio.run(main())
