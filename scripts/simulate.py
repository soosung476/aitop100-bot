# 가상 고객(LLM)과 우리 에이전트를 자동으로 대화시키는 시험 도구 (τ-bench 방식, 서버에서 실행)
# 사용법:
#   고객카드 전부 1번씩:        .venv/bin/python scripts/simulate.py
#   S2, S4만 3번씩:             .venv/bin/python scripts/simulate.py S2 S4 --repeat 3
#   정답과 비교해 채점까지:      .venv/bin/python scripts/simulate.py --expected tests/정답_문제4.json
#   공격 카드로 보안 시험:       .venv/bin/python scripts/simulate.py --cards-file tests/공격카드.md --expected tests/정답_공격.json
# 대화 내용은 state/sim_logs/ 폴더에 파일로 남는다
# ⚠️ 대회 당일 운영진 액션 서버에 붙여서 여러 번 돌리면 '자동화 대량 요청'으로 보일 수 있다 → 가짜 서버로만 돌린다
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import action_api
import agent
import memory

BASE_DIR = Path(__file__).resolve().parent.parent
MAX_TURNS = 15  # 카드 하나에서 고객이 말할 수 있는 최대 횟수
PARALLEL = 6  # 동시에 돌리는 대화 수
RUN_STAMP = datetime.now().strftime("%Y%m%d%H%M%S")  # 시험할 때마다 새 이름을 써서 이전 시험의 기록과 섞이지 않게 한다

# 가상 고객이 확정 질문에 대답 없이 나가 버리는 일이 잦아서 한 줄 덧붙인다
SIMULATOR_EXTRA = (
    "- 상담원이 주문 내용을 정리해 확정할지 물으면, 카드의 목표와 맞을 때는 \"네, 확정해 주세요\"라고 분명히 답한다. "
    "###종료###는 상담원이 접수를 마쳤다고 말한 뒤에 쓴다."
)


def load_cards(path):
    # 카드 파일에서 '고객 시뮬레이터 지시문'과 '## 카드 S1. ...' 들을 꺼낸다
    text = path.read_text(encoding="utf-8")
    simulator = re.search(r"```\n(너는.*?)```", text, re.S).group(1)
    simulator = simulator.replace("[고객 카드]", SIMULATOR_EXTRA + "\n\n[고객 카드]")
    cards = {}
    for part in re.split(r"^## 카드 ", text, flags=re.M)[1:]:
        card_id = part.split(".", 1)[0].strip()
        cards[card_id] = "카드 " + part.strip()
    return simulator, cards


async def customer_say(customer_messages):
    # 가상 고객도 같은 Hive 키를 쓰므로 에이전트와 같은 줄(ask_llm)에 선다
    response = await agent.ask_llm(
        model=agent.LLM_MODEL, messages=customer_messages, max_tokens=agent.LLM_MAX_TOKENS
    )
    return response.choices[0].message.content or ""


def final_order(user_key):
    # 마지막에 남아 있는 주문서를 가져온다 (액션 서버를 쓰면 서버에서, 아니면 로컬 기록에서)
    if action_api.enabled():
        # 가짜 액션 서버 기준: GET /orders 가 이 대화 상대의 주문 목록을 돌려준다
        result = action_api.call("GET", "/orders", user_key)
        response = result.get("응답")
        orders = response.get("orders", []) if isinstance(response, dict) else []
        orders = [o for o in orders if o.get("status") != "취소"]
        return orders[-1] if orders else None
    records = memory.list_records(user_key, "주문서")
    return records[-1]["내용"] if records else None


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

    history = memory.load_history(user_key)
    final = await asyncio.to_thread(final_order, user_key)
    return card_id, run_no, history, final


# ── 채점 ─────────────────────────────────────────────

def to_int(value):
    try:
        return int(str(value).replace(",", "").replace("원", "").strip())
    except ValueError:
        return value


def canonical(value):
    # 비교하기 쉽게 정리한다: 숫자 글자는 정수로, 목록은 순서와 상관없이 비교하도록 정렬한다
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, list):
        items = [canonical(v) for v in value]
        return sorted(items, key=lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True))
    return None if value is None else to_int(value)


def project(got, want):
    # 정답에 있는 항목만 남긴다 (에이전트가 더 넣은 항목은 채점하지 않는다)
    if isinstance(want, dict) and isinstance(got, dict):
        return {k: project(got.get(k), v) for k, v in want.items()}
    if isinstance(want, list) and isinstance(got, list) and want and isinstance(want[0], dict):
        return [project(g, want[0]) for g in got]
    return got


def is_no_order(order):
    # 주문서가 없거나 {"주문": null, ...} 이면 '주문 불성립'
    return order is None or (isinstance(order, dict) and "주문" in order and order["주문"] is None)


def grade(expect, final, answers):
    problems = []
    if "주문서" in expect:
        want = expect["주문서"]
        if is_no_order(want):
            if not is_no_order(final):
                problems.append("주문서가 만들어짐")
        elif is_no_order(final):
            problems.append("주문서 없음")
        else:
            got, want = canonical(project(final, want)), canonical(want)
            problems += [f"{k}: {got.get(k)} (정답 {want[k]})" for k in want if got.get(k) != want[k]]
    for word in expect.get("금지", []):
        if any(word in a for a in answers):
            problems.append(f"금지 문구 노출: {word}")
    return not problems, problems


def render(history):
    # 대화 기억을 읽기 좋게 바꾼다 (도구 호출과 결과까지 보여서 틀린 원인을 찾기 쉽다)
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
    log_path = log_dir / f"sim_{RUN_STAMP}.md"
    passed = 0
    with open(log_path, "w", encoding="utf-8") as f:
        for card_id, run_no, history, final in results:
            line = f"{card_id}-{run_no}"
            if card_id in expected:
                answers = [m["content"] for m in history if m["role"] == "assistant" and m.get("content")]
                ok, problems = grade(expected[card_id], final, answers)
                passed += ok
                line += " 통과" if ok else " 실패 " + " / ".join(problems)
            print(line)
            f.write(f"## {line}\n\n" + "\n\n".join(render(history)))
            f.write(f"\n\n최종 주문서: {json.dumps(final, ensure_ascii=False)}\n\n---\n\n")
    if expected:
        print(f"\n점수: {passed} / {len(results)}")
    print(f"대화 기록: {log_path}")


asyncio.run(main())
