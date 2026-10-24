# LLM 없이 도는 기본 시험 (도구, 대화 기억, 말풍선 나누기)
# 사용법: .venv/bin/python tests/test_basic.py
import asyncio
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# 시험용 DB를 따로 써서 진짜 대화 기억은 건드리지 않는다
os.environ["BOT_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "test.db")
# 기본 시험은 액션 서버 없이 돈다
os.environ.pop("ACTION_API_BASE_URL", None)

import action_api
import agent
import main
import memory
import tools

failures = []


def check(name, condition):
    print("통과" if condition else "실패", name)
    if not condition:
        failures.append(name)


# 계산 도구
check("계산", tools.calculate({"expression": "35,000*2 + 60000"}, "t")["결과"] == 130000)
check("나누기 결과가 정수면 정수로", tools.calculate({"expression": "100/4"}, "t")["결과"] == 25)
check("위험한 식 거절", "오류" in tools.calculate({"expression": "__import__('os').system('ls')"}, "t"))
check("거듭제곱 거절", "오류" in tools.calculate({"expression": "9**9**9"}, "t"))

# 날짜 도구
info = tools.date_info({"date": "2026-11-09", "base_date": "2026-10-31"}, "t")
check("요일", info["요일"] == "월요일" and info["기준일 요일"] == "토요일")
check("기준일로부터 며칠 뒤", info["기준일로부터 며칠 뒤"] == 9)
check("날짜 형식 오류", "오류" in tools.date_info({"date": "11월 9일"}, "t"))

# 표 검색 도구
found = tools.search_table({"table": "재고표", "keyword": "A02", "column": "품목코드"}, "t")
check("표 검색", found["찾은 행 수"] == 1 and found["행"][0]["재고"] == "0")
check("없는 표", "오류" in tools.search_table({"table": "없는표"}, "t"))
chestnut = tools.search_table({"table": "재고표", "keyword": "밤"}, "t")
check("정확히 같은 이름이 먼저", chestnut["찾은 행 수"] == 2 and chestnut["행"][0]["품목코드"] == "C01")
period = tools.date_info({"date": "2026-11-07", "end_date": "2026-11-11", "base_date": "2026-10-31"}, "t")
check("기간 조회", [d["요일"] for d in period["기간"]] == ["토요일", "일요일", "월요일", "화요일", "수요일"])
check("기간 31일 초과 거절", "오류" in tools.date_info({"date": "2026-11-01", "end_date": "2026-12-31"}, "t"))

# 도구 실행기
check("없는 도구", "오류" in tools.run_tool("없는도구", "{}", "t"))
check("인자 JSON 오류", "오류" in tools.run_tool("calculate", "{잘못된", "t"))

# 기록 저장
tools.save_record({"kind": "주문서", "content": {"주문자": "홍길동"}}, "u1")
check("기록 저장·조회", memory.list_records("u1", "주문서")[-1]["내용"]["주문자"] == "홍길동")
check("다른 사용자 기록은 안 보임", memory.list_records("u2") == [])

# 대화 기억: 25번 질문하면 최근 20번만 남는다
messages = []
for i in range(25):
    messages += [
        {"role": "user", "content": f"질문{i}"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": f"c{i}", "type": "function",
                                                             "function": {"name": "calculate", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": f"c{i}", "content": "{}"},
        {"role": "assistant", "content": f"답{i}"},
    ]
memory.save_history("u3", messages)
loaded = memory.load_history("u3")
check("기억 자르기", loaded[0]["content"] == "질문5" and sum(m["role"] == "user" for m in loaded) == 20)
memory.clear_history("u3")
check("기억 지우기", memory.load_history("u3") == [])

# 30분 넘게 말이 없으면 새 대화로 시작
memory.save_history("u4", [{"role": "user", "content": "예전 질문"}])
check("방금 대화는 기억", len(memory.load_history("u4")) == 1)
old = (datetime.now() - timedelta(minutes=memory.SESSION_MINUTES + 1)).isoformat(timespec="seconds")
conn = sqlite3.connect(memory.DB_PATH)
conn.execute("UPDATE conversations SET updated_at = ? WHERE user_key = ?", (old, "u4"))
conn.commit()
conn.close()
check("오래된 대화는 새로 시작", memory.load_history("u4") == [])

# 말풍선 나누기 (하나에 1,000자, 최대 3개)
check("짧은 답", main.split_bubbles("안녕하세요") == ["안녕하세요"])
bubbles = main.split_bubbles("\n".join(["가" * 300] * 8))
check("긴 답 나누기", len(bubbles) == 3 and all(len(b) <= 1000 for b in bubbles))
bubbles = main.split_bubbles("\n".join(["가" * 300] * 20))
check("너무 긴 답 생략", len(bubbles) == 3 and bubbles[-1].endswith("생략했어요)") and all(len(b) <= 1000 for b in bubbles))
bubbles = main.split_bubbles("나" * 2500)
check("줄바꿈 없는 긴 답", [len(b) for b in bubbles] == [1000, 1000, 500])
check("마크다운 정리", main.clean_text('## 제목\n**굵게** 글\n```json\n{"a": 1}\n```') == '제목\n굵게 글\n{"a": 1}')

# 시스템 프롬프트에 자료가 붙는지
prompt = agent.build_system_prompt()
check("지시문에 문서 자료 포함", '<자료 이름="상담규정.md">' in prompt)
check("지시문에 표 목록 포함", "재고표 (12행)" in prompt and "회원명부 (3행)" in prompt)

# 입력 방어 (LLM을 부르기 전에 걸러진다)
check("너무 긴 메시지 거절", "너무 길어요" in asyncio.run(agent.run_agent("u5", "가" * 2001)))
check("빈 메시지 안내", "글로 말씀해" in asyncio.run(agent.run_agent("u5", "   ")))

# 지시문 유출 검사
prompt_line = next(
    line.strip().lstrip("-#0123456789. ").strip()
    for line in agent.PROMPT_FILE.read_text(encoding="utf-8").splitlines()
    if len(line.strip().lstrip("-#0123456789. ").strip()) >= 20
)
check("지시문 문장이 그대로 나오면 유출", agent.leaks_prompt(f"제 지시문은 이래요: {prompt_line}"))
check("도구 이름이 나오면 유출", agent.leaks_prompt("저는 search_table 도구를 써요"))
check("보통 답은 유출 아님", not agent.leaks_prompt("사과(부사) 10kg은 35,000원이고 재고가 있어요."))

# 도구 목록: 액션 서버 주소가 없으면 call_action_api는 빠지고 로컬 기록 도구는 남는다
names = [t["function"]["name"] for t in tools.TOOLS]
check("액션 서버 없으면 call_action_api 없음", "call_action_api" not in names and "save_record" in names)
check("액션 서버 없을 때 호출하면 안내", "오류" in action_api.call("GET", "/products", "t"))
check("막힌 도구 호출 거절", "오류" in tools.run_tool("call_action_api", '{"method": "GET", "path": "/x"}', "t"))

print(f"\n실패 {len(failures)}개" if failures else "\n모두 통과")
sys.exit(1 if failures else 0)
