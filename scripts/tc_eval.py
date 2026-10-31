# 공개 TC로 에이전트를 자동 시험한다 (가상 고객 LLM + 채점 LLM, 서버에서 실행)
# 사용법: .venv/bin/python scripts/tc_eval.py [L-03 L-05 ...] [--parallel 3]
# 액션 API 문서가 연습 호출을 허용한다(60초당 100번, 누적 한도 없음). 호출 수는 TC당 10~20번이다
import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import AsyncOpenAI

import action_api
import agent
import main as bot
import memory

BASE_DIR = Path(__file__).resolve().parent.parent
TC_DIR = BASE_DIR / "tests" / "public_tc"
MAX_TURNS = 7
RUN_STAMP = datetime.now().strftime("%m%d-%H%M%S")
OUT_DIR = BASE_DIR / "state" / "tc_eval" / RUN_STAMP

# 가상 고객·채점은 상담 응답 시간과 상관없으니 시간 제한을 넉넉히 둔다
eval_llm = AsyncOpenAI(base_url=agent.llm.base_url, api_key=agent.llm.api_key, timeout=150, max_retries=3)
eval_slots = asyncio.Semaphore(2)


async def ask_eval(**kwargs):
    async with eval_slots:
        return await eval_llm.chat.completions.create(**kwargs)


# 액션 API 호출을 사용자별로 기록한다
calls_by_user = {}
real_call = action_api.call


def recording_call(method, path, user_key, query=None, body=None, case_id=""):
    result = real_call(method, path, user_key, query, body, case_id)
    calls_by_user.setdefault(user_key, []).append(
        {"method": method, "path": path, "query": query, "body": body, "status": result.get("상태코드")}
    )
    return result


action_api.call = recording_call


def load_tc(tc_id):
    text = (TC_DIR / f"{tc_id}.md").read_text(encoding="utf-8")
    first = text.split("#### 초기 대화", 1)[1].split("#### 시나리오", 1)[0].strip()
    situation = text.split("###### 상황", 1)[1].split("###### 기대 대응", 1)[0].strip()
    expected = text.split("###### 기대 대응", 1)[1].strip()
    name = re.search(r"인입 계정: .*?· (.+?) ·", first)
    return {"id": tc_id, "first": first, "situation": situation, "expected": expected, "name": name.group(1) if name else ""}


def customer_orders(tc):
    # 가상 고객에게 자기 주문 목록을 알려 준다 (실제 고객은 주문번호를 알고 있다)
    user = f"tc:{tc['id']}:lookup"
    memory.set_case(user, tc["id"])
    members = real_call("GET", "/api/members", user, {"name": tc["name"]}).get("응답") or []
    lines = []
    for member in members if isinstance(members, list) else []:
        lines.append(f"회원번호 {member['member_id']} 전화 {member['phone']}")
        orders = real_call("GET", "/api/orders", user, {"member_id": member["member_id"]}).get("응답") or []
        for order in orders if isinstance(orders, list) else []:
            items = ", ".join(f"{i['name']} {i['qty']}개" for i in order["items"])
            lines.append(f"주문번호 {order['order_no']}: {order['ordered_at'][:10]} {items} {order['amount']}원 {order['status']}")
    return "\n".join(lines)


async def customer_say(tc, orders, transcript):
    system = (
        "너는 쇼핑몰 상담 채팅의 고객이다. 아래 [상황]의 고객처럼 짧은 구어체로 한두 문장만 말한다. 상담원 역할을 하지 않는다.\n"
        "상담원이 물은 것에는 [상황]과 [내 주문]에 있는 사실로 답한다. 대상 주문번호를 물으면 상황에 맞는 주문의 번호를 말한다. "
        "없는 사실을 지어내지 않는다. 상세주소를 물으면 그럴듯한 주소를 지어 답해도 된다.\n"
        "상황에 적힌 고객의 반응(되묻기, 항의, 선택)이 있으면 차례대로 한 번씩 보인다.\n"
        "궁금한 것이 해결됐거나 더 할 말이 없으면 ###종료### 한 단어만 쓴다.\n\n"
        f"[상황]\n{tc['situation']}\n\n[내 주문]\n{orders or '없음'}"
    )
    # 고객 입장에서는 상담원 말이 user, 자기 말이 assistant다
    messages = [{"role": "system", "content": system}]
    for who, said in transcript:
        messages.append({"role": "assistant" if who == "고객" else "user", "content": said})
    response = await ask_eval(model=agent.LLM_MODEL, messages=messages, max_tokens=3000)
    return (response.choices[0].message.content or "###종료###").strip()


async def judge(tc, transcript, calls):
    log_text = "\n".join(f"{who}: {said}" for who, said in transcript)
    call_text = "\n".join(json.dumps(c, ensure_ascii=False) for c in calls) or "없음"
    prompt = (
        "고객 상담 AI의 대화를 기대 대응 항목별로 엄격하게 채점한다. 항목마다 충족 여부를 판단한다. "
        "API 번호와 경로 대응: API-01 /api/products/{sku}, API-03 /api/lots/{id}, API-04 /api/lots/{id}/investigation, "
        "API-06 /api/tickets?lot_id, API-07 /api/orders/{no}, API-08 /api/orders?member_id, API-10 /api/shipments/{id}, API-11 /api/shipments?order_no, "
        "API-12 /api/members/{id}, API-13 /api/members?name, API-20 /api/promos/{code}, API-24 address-change-requests, API-25 schedule-change-requests, "
        "API-27 expedite-requests, API-28 reship-requests, API-29 /api/refunds, API-32 cash-receipt-requests, API-33 coupon-issue-requests, API-35 /api/escalations.\n"
        '결과는 JSON만 출력한다: {"items":[{"no":1,"ok":true,"why":"짧은 이유"}]}\n\n'
        f"[기대 대응]\n{tc['expected']}\n\n[대화]\n{log_text}\n\n[API 호출 기록]\n{call_text}"
    )
    response = await ask_eval(
        model=agent.LLM_MODEL, messages=[{"role": "user", "content": prompt}], max_tokens=12000
    )
    content = response.choices[0].message.content or ""
    match = re.search(r"\{.*\}", content, re.S)
    try:
        return json.loads(match.group(0))["items"]
    except Exception:
        return [{"no": 0, "ok": False, "why": "채점 실패: " + content[:100]}]


async def run_tc(tc_id, slots):
    async with slots:
        tc = load_tc(tc_id)
        user = f"tc:{tc_id}:{RUN_STAMP}"
        calls_by_user[user] = []
        orders = await asyncio.to_thread(customer_orders, tc)
        memory.clear_history(user)
        transcript = []
        latencies = []
        bubbles = []
        text = tc["first"]
        for turn in range(MAX_TURNS):
            transcript.append(("고객", text))
            started = time.time()
            try:
                answer = await asyncio.wait_for(agent.run_agent(user, text), timeout=bot.AGENT_TIMEOUT)
            except asyncio.TimeoutError:
                answer = "(시간 초과)"
            except Exception as e:
                answer = f"(오류 {e.__class__.__name__}: {e})"
            latencies.append(time.time() - started)
            parts = bot.split_bubbles(bot.clean_text(answer))
            bubbles.extend(parts)
            transcript.append(("상담원", answer))
            text = await customer_say(tc, orders, transcript)
            # 가상 고객이 첫 답에서 바로 나가 버리면 시험이 안 되므로 한 번 더 말하게 한다
            if "###종료###" in text and turn == 0:
                text = await customer_say(tc, orders, transcript + [("고객", "(아직 상담이 끝나지 않았다. 상담원 질문에 답한다)")])
            if "###종료###" in text:
                break
        calls = calls_by_user[user]
        items = await judge(tc, transcript, calls)
        passed = sum(1 for i in items if i.get("ok"))
        result = {
            "id": tc_id, "score": f"{passed}/{len(items)}", "items": items,
            "latency": [round(x, 1) for x in latencies], "bubbles": len(bubbles),
            "avg_chars": round(sum(len(b) for b in bubbles) / max(len(bubbles), 1)),
            "transcript": transcript, "calls": calls,
        }
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUT_DIR / f"{tc_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{tc_id:8} {result['score']:6} 최대 {max(latencies):5.1f}초 평균 {sum(latencies)/len(latencies):5.1f}초 "
              f"말풍선 {len(bubbles)}개 평균 {result['avg_chars']}자 호출 {len(calls)}번", flush=True)
        for item in items:
            if not item.get("ok"):
                print(f"   ✗ {item.get('no')}: {str(item.get('why'))[:150]}", flush=True)
        return result


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--parallel", type=int, default=3)
    args = parser.parse_args()
    ids = args.ids or sorted(p.stem for p in TC_DIR.glob("*.md"))
    # 접수 기록이 남아 있으면 조회 결과가 달라지므로 처음 상태로 되돌린다
    resp = action_api.client.post(action_api.BASE_URL + "/api/action-data/reset", headers={action_api.HEADER_NAME: action_api.HEADER_VALUE})
    print("데이터 초기화", resp.status_code, flush=True)
    slots = asyncio.Semaphore(args.parallel)
    started = time.time()
    results = [r for r in await asyncio.gather(*[run_tc(i, slots) for i in ids], return_exceptions=True) if isinstance(r, dict)]
    all_lat = sorted(x for r in results for x in r["latency"])
    passed = sum(sum(1 for i in r["items"] if i.get("ok")) for r in results)
    total = sum(len(r["items"]) for r in results)
    p95 = all_lat[int(len(all_lat) * 0.95) - 1] if all_lat else 0
    print(f"\n합계 {passed}/{total}  p95 {p95:.1f}초  케이스당 말풍선 {sum(r['bubbles'] for r in results)/len(results):.1f}개  "
          f"평균 {sum(r['avg_chars'] for r in results)/len(results):.0f}자  {time.time()-started:.0f}초 걸림  기록 {OUT_DIR}", flush=True)


asyncio.run(main())
