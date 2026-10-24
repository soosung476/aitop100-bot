# 가상 고객(LLM)과 우리 에이전트를 자동으로 대화시키는 시험 도구 (τ-bench 방식, 서버에서 실행)
# 사용법:
#   고객카드 전부 1번씩:        .venv/bin/python scripts/simulate.py
#   S2, S4만 3번씩:             .venv/bin/python scripts/simulate.py S2 S4 --repeat 3
#   정답과 비교해 채점까지:      .venv/bin/python scripts/simulate.py --expected tests/정답_문제4.json
# 대화 내용은 state/sim_logs/ 폴더에 파일로 남는다
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import agent
import memory

BASE_DIR = Path(__file__).resolve().parent.parent
MAX_TURNS = 15  # 카드 하나에서 고객이 말할 수 있는 최대 횟수
PARALLEL = 6  # 동시에 돌리는 대화 수


def load_cards(path):
    # 고객카드.md에서 '고객 시뮬레이터 지시문'과 '## 카드 S1. ...' 들을 꺼낸다
    text = path.read_text(encoding="utf-8")
    simulator = re.search(r"```\n(너는.*?)```", text, re.S).group(1)
    cards = {}
    for part in re.split(r"^## 카드 ", text, flags=re.M)[1:]:
        card_id = part.split(".", 1)[0].strip()
        cards[card_id] = "카드 " + part.strip()
    return simulator, cards


async def customer_say(customer_messages):
    response = await agent.llm.chat.completions.create(
        model=agent.LLM_MODEL, messages=customer_messages, max_tokens=agent.LLM_MAX_TOKENS
    )
    return response.choices[0].message.content or ""


RUN_STAMP = datetime.now().strftime("%Y%m%d%H%M%S")  # 시험할 때마다 새 이름을 써서 이전 시험의 기록과 섞이지 않게 한다


async def run_card(simulator, card_id, card, run_no):
    user_key = f"sim:{RUN_STAMP}:{card_id}:{run_no}"
    memory.clear_history(user_key)
    # 고객 LLM 입장에서는 자기 말이 assistant, 상담원 말이 user다
    customer = [
        {"role": "system", "content": simulator.replace("(여기에 카드 붙여넣기)", card)},
        {"role": "user", "content": "(상담원과 연결되었습니다. 고객으로서 첫 마디를 하세요.)"},
    ]
    answer = ""
    for _ in range(MAX_TURNS):
        said = await customer_say(customer)
        finished = "###종료###" in said
        said = said.replace("###종료###", "").strip()
        if said:
            answer = await agent.run_agent(user_key, said)
        if finished:
            break
        customer.append({"role": "assistant", "content": said or "..."})
        customer.append({"role": "user", "content": answer or "..."})

    records = memory.list_records(user_key, "주문서")
    final = records[-1]["내용"] if records else "(저장된 주문서 없음)"
    return card_id, run_no, render(memory.load_history(user_key)), final


def render(history):
    # 저장된 대화 기억을 읽기 좋게 바꾼다 (도구 호출과 결과까지 보여서 틀린 원인을 찾기 쉽다)
    lines = []
    for m in history:
        if m["role"] == "user":
            lines.append(f"고객: {m['content']}")
        elif m["role"] == "tool":
            lines.append(f"    [결과] {m['content'][:300]}")
        elif m.get("tool_calls"):
            for call in m["tool_calls"]:
                lines.append(f"    [도구] {call['function']['name']} {call['function']['arguments']}")
        else:
            lines.append(f"상담원: {m['content']}")
    return lines


def to_int(value):
    try:
        return int(str(value).replace(",", "").replace("원", "").strip())
    except ValueError:
        return value


def normalize(order):
    # 비교하기 쉽게 바꾼다: 숫자는 정수로, 품목은 (코드, 수량, 금액) 묶음으로. 주문 불성립은 None
    if not isinstance(order, dict) or ("주문" in order and order["주문"] is None):
        return None
    items = sorted(
        (str(item.get("코드")), to_int(item.get("수량")), to_int(item.get("금액")))
        for item in order.get("품목", [])
    )
    return {
        "주문자": order.get("주문자"),
        "연락처": order.get("연락처"),
        "배송지": order.get("배송지"),
        "희망배송일": order.get("희망배송일"),
        "결제방식": order.get("결제방식"),
        "품목": items,
        "배송비": to_int(order.get("배송비")),
        "총액": to_int(order.get("총액")),
    }


def grade(final, expected):
    # 정답이 '주문 불성립'이면 주문서가 없거나 null이어야 통과, 아니면 모든 항목이 같아야 통과
    got = None if isinstance(final, str) else normalize(final)
    want = normalize(expected)
    if want is None:
        return got is None, [] if got is None else ["주문서가 만들어짐"]
    if got is None:
        return False, ["주문서 없음"]
    wrong = [f"{k}: {got[k]} (정답 {want[k]})" for k in want if got[k] != want[k]]
    return not wrong, wrong


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cards", nargs="*", help="돌릴 카드 (예: S1 S4). 비우면 전부")
    parser.add_argument("--repeat", type=int, default=1, help="카드마다 몇 번 돌릴지")
    parser.add_argument("--cards-file", default=str(BASE_DIR / "tests" / "고객카드.md"))
    parser.add_argument("--expected", default="", help="정답 JSON 파일 (주면 채점)")
    args = parser.parse_args()

    simulator, cards = load_cards(Path(args.cards_file))
    chosen = args.cards or list(cards)
    expected = json.loads(Path(args.expected).read_text(encoding="utf-8")) if args.expected else {}

    limit = asyncio.Semaphore(PARALLEL)

    async def limited(card_id, run_no):
        async with limit:
            return await run_card(simulator, card_id, cards[card_id], run_no)

    results = await asyncio.gather(*[limited(c, r) for c in chosen for r in range(1, args.repeat + 1)])

    log_dir = BASE_DIR / "state" / "sim_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"sim_{datetime.now():%Y%m%d_%H%M%S}.md"
    passed = 0
    with open(log_path, "w", encoding="utf-8") as f:
        for card_id, run_no, transcript, final in results:
            line = f"{card_id}-{run_no}"
            if card_id in expected:
                ok, wrong = grade(final, expected[card_id])
                passed += ok
                line += " 통과" if ok else " 실패 " + " / ".join(wrong)
            print(line)
            f.write(f"## {line}\n\n" + "\n\n".join(transcript))
            f.write(f"\n\n최종 주문서: {json.dumps(final, ensure_ascii=False)}\n\n---\n\n")
    if expected:
        print(f"\n점수: {passed} / {len(results)}")
    print(f"대화 기록: {log_path}")


asyncio.run(main())
