# 에이전트가 쓰는 도구(함수) 모음 ← 대회 당일 주로 고치는 곳
# 도구 하나 = ① LLM에게 보여 주는 설명(TOOLS 목록) + ② 실제로 실행하는 파이썬 함수(FUNCTIONS)
# 모든 도구 함수는 (args, user_key)를 받는다. args는 LLM이 채운 인자(딕셔너리), user_key는 대화 상대 구분값이다
import ast
import csv
import json
import operator
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import action_api
import memory

# 자료 폴더: 기본은 data, 연습용 다른 자료로 시험할 때는 BOT_DATA_DIR 환경변수로 바꾼다
DATA_DIR = Path(__file__).parent / os.getenv("BOT_DATA_DIR", "data")
WEEKDAYS = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
MAX_ROWS = 50  # 표 검색 결과를 한 번에 최대 몇 행까지 돌려줄지


# ── 자료 읽기 ─────────────────────────────────────────
# data 폴더의 .csv 파일을 모두 표로 읽어 둔다 → {"재고표": [{"마을": "교동", ...}, ...], ...}
# (엑셀에서 저장한 CSV는 cp949인 경우가 많아서 utf-8로 안 읽히면 cp949로 다시 읽는다)

def read_csv(path):
    for encoding in ("utf-8-sig", "cp949"):
        try:
            with open(path, encoding=encoding, newline="") as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path.name} 파일의 글자 인코딩을 읽을 수 없습니다")


TABLES = {path.stem: read_csv(path) for path in sorted(DATA_DIR.glob("*.csv"))}


def describe_tables():
    lines = []
    for name, rows in TABLES.items():
        columns = ", ".join(rows[0].keys()) if rows else "(비어 있음)"
        lines.append(f"- {name} ({len(rows)}행): {columns}")
    return "\n".join(lines) or "(표 없음)"


def today():
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


# ── 도구 함수 ─────────────────────────────────────────

def search_table(args, user_key):
    name = str(args.get("table", "")).strip()
    keyword = str(args.get("keyword", "")).strip()
    column = str(args.get("column", "")).strip()
    if name not in TABLES:
        return {"오류": f"'{name}' 표는 없습니다.", "있는 표": list(TABLES)}

    rows = TABLES[name]
    if keyword and column:
        rows = [r for r in rows if keyword in str(r.get(column, ""))]
    elif keyword:
        rows = [r for r in rows if any(keyword in str(v) for v in r.values())]
    # 검색어와 정확히 같은 값이 있는 행을 맨 앞으로 (예: '밤'으로 찾으면 '고구마(밤)'보다 '밤'이 먼저)
    if keyword:
        rows = sorted(rows, key=lambda r: keyword not in [str(v) for v in r.values()])

    result = {"표": name, "찾은 행 수": len(rows), "행": rows[:MAX_ROWS]}
    if len(rows) > MAX_ROWS:
        result["안내"] = f"앞의 {MAX_ROWS}행만 보여 줍니다. keyword로 더 좁혀서 찾으세요."
    return result


# 계산에 허용하는 기호: + - * / // % 와 괄호 (거듭제곱 ** 은 너무 큰 수로 서버를 멈출 수 있어 뺐다)
OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def evaluate(node):
    # ast: 파이썬이 수식을 나무 구조로 쪼갠 것. 숫자와 허용한 기호만 계산하고 나머지는 거절해서 안전하다
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](evaluate(node.left), evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPERATORS:
        return OPERATORS[type(node.op)](evaluate(node.operand))
    raise ValueError("숫자와 + - * / // % ( ) 만 쓸 수 있습니다")


def calculate(args, user_key):
    expression = str(args.get("expression", "")).replace(",", "").strip()
    if not expression or len(expression) > 300:
        return {"오류": "계산식이 비었거나 너무 깁니다."}
    try:
        result = evaluate(ast.parse(expression, mode="eval").body)
    except (ValueError, SyntaxError, ZeroDivisionError) as e:
        return {"오류": f"계산할 수 없는 식입니다: {e}"}
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return {"식": expression, "결과": result}


def date_info(args, user_key):
    try:
        target = date.fromisoformat(str(args.get("date", "")).strip())
        base_text = str(args.get("base_date", "")).strip()
        base = date.fromisoformat(base_text) if base_text else today()
        end_text = str(args.get("end_date", "")).strip()
        end = date.fromisoformat(end_text) if end_text else None
    except ValueError:
        return {"오류": "날짜는 YYYY-MM-DD 형식으로 주세요."}

    result = {
        "날짜": target.isoformat(),
        "요일": WEEKDAYS[target.weekday()],
        "기준일": base.isoformat(),
        "기준일 요일": WEEKDAYS[base.weekday()],
        "기준일로부터 며칠 뒤": (target - base).days,
    }
    # end_date를 주면 date부터 end_date까지 날짜마다 요일을 보여 준다 (가장 가까운 가능한 날을 찾을 때 쓴다)
    if end:
        if not 0 <= (end - target).days <= 31:
            return {"오류": "end_date는 date와 같거나 뒤여야 하고, 기간은 31일 이내여야 합니다."}
        result["기간"] = [
            {
                "날짜": (target + timedelta(days=i)).isoformat(),
                "요일": WEEKDAYS[(target + timedelta(days=i)).weekday()],
                "기준일로부터 며칠 뒤": (target + timedelta(days=i) - base).days,
            }
            for i in range((end - target).days + 1)
        ]
    return result


def save_record(args, user_key):
    kind = str(args.get("kind", "")).strip() or "기록"
    content = args.get("content")
    if content is None:
        return {"오류": "저장할 content가 없습니다."}
    record_id = memory.add_record(user_key, kind, content)
    return {"저장됨": True, "기록번호": record_id, "종류": kind}


def get_records(args, user_key):
    kind = str(args.get("kind", "")).strip()
    return {"기록": memory.list_records(user_key, kind)}


def call_action_api(args, user_key):
    return action_api.call(
        args.get("method", "GET"), args.get("path", ""), user_key, args.get("query"), args.get("body")
    )


# ── LLM에게 보여 주는 도구 설명 ───────────────────────
# description을 구체적으로 쓸수록 LLM이 도구를 알맞게 고른다

ALL_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_table",
            "description": "자료 표(CSV)에서 행을 찾는다. keyword를 비우면 표 전체를 돌려준다.\n사용 가능한 표:\n" + describe_tables(),
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "표 이름 (예: 재고표)"},
                    "keyword": {"type": "string", "description": "찾을 글자. 비우면 전체 행"},
                    "column": {"type": "string", "description": "keyword를 찾을 열 이름. 비우면 모든 열에서 찾는다"},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "금액, 수량, 합계 같은 계산을 정확히 한다. 암산하지 말고 이 도구를 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "계산식 (예: 35000*2 + 60000)"},
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "date_info",
            "description": (
                "날짜의 요일과, 기준일로부터 며칠 뒤인지 알려 준다. 날짜·요일은 추측하지 말고 이 도구로 확인한다. "
                "end_date를 주면 date부터 end_date까지 날짜마다 요일을 함께 보여 준다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "확인할 날짜 (YYYY-MM-DD)"},
                    "base_date": {"type": "string", "description": "기준일 (YYYY-MM-DD). 비우면 오늘"},
                    "end_date": {"type": "string", "description": "기간의 마지막 날 (YYYY-MM-DD, 선택, 31일 이내)"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_record",
            "description": "확정된 결과(예: 주문서)를 저장한다. 고객이 확정했을 때만 쓴다. 내용이 바뀌면 새로 저장하며, 마지막에 저장한 것이 최종이다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "기록 종류 (예: 주문서)"},
                    "content": {"type": "object", "description": "저장할 내용 (JSON 객체)"},
                },
                "required": ["kind", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_records",
            "description": "지금 대화 상대에 대해 저장한 기록을 불러온다. 이전 주문을 확인하거나 고칠 때 쓴다.",
            "parameters": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "description": "기록 종류 (비우면 전부)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "call_action_api",
            "description": (
                "운영진 액션 서버(API)를 부른다. 쓸 수 있는 주소와 형식은 참고 자료의 API 문서를 따른다. "
                "인증 정보는 자동으로 붙는다. 결과의 상태코드가 400 이상이면 거절된 것이니 응답 내용을 읽고 대처한다."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
                    "path": {"type": "string", "description": "주소 경로 (예: /products)"},
                    "query": {"type": "object", "description": "주소 뒤에 붙는 조건 (예: {\"keyword\": \"사과\"})"},
                    "body": {"type": "object", "description": "POST·PUT·PATCH로 보낼 JSON 본문"},
                },
                "required": ["method", "path"],
            },
        },
    },
]

# 도구 이름 → 실제로 실행할 함수
FUNCTIONS = {
    "search_table": search_table,
    "calculate": calculate,
    "date_info": date_info,
    "save_record": save_record,
    "get_records": get_records,
    "call_action_api": call_action_api,
}

# 상황에 맞는 도구만 LLM에게 보여 준다
# - 표 자료(CSV)가 없으면 search_table을 뺀다
# - 액션 서버를 쓰면 주문의 진짜 저장소는 액션 서버이므로 로컬 기록 도구(save_record, get_records)를 뺀다
ACTIVE = set(FUNCTIONS)
if not TABLES:
    ACTIVE.discard("search_table")
if action_api.enabled():
    ACTIVE -= {"save_record", "get_records"}
else:
    ACTIVE.discard("call_action_api")
TOOLS = [tool for tool in ALL_TOOLS if tool["function"]["name"] in ACTIVE]


def run_tool(name, arguments, user_key):
    # LLM이 요청한 도구를 실행하고 결과를 JSON 글자로 돌려준다
    # 실패해도 에러를 결과로 돌려줘서 LLM이 스스로 고쳐 다시 시도할 수 있게 한다
    if name not in ACTIVE:
        result = {"오류": f"'{name}' 도구는 없습니다.", "있는 도구": sorted(ACTIVE)}
    else:
        try:
            args = json.loads(arguments or "{}")
            result = FUNCTIONS[name](args, user_key)
        except Exception as e:
            result = {"오류": f"도구 실행 중 문제가 생겼습니다: {e}"}
    return json.dumps(result, ensure_ascii=False)
