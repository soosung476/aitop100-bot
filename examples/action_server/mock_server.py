# 연습용 가짜 액션 서버 — 대회 당일 운영진이 주는 액션 서버(API)를 흉내 낸다
# 실행 (서버에서): .venv/bin/uvicorn --app-dir examples/action_server mock_server:app --host 127.0.0.1 --port 9000
# 봇이 이 서버를 쓰게 하려면 .env(또는 시험 명령)에 아래를 넣는다
#   ACTION_API_BASE_URL=http://127.0.0.1:9000
#   ACTION_API_HEADER_NAME=X-API-Key
#   ACTION_API_HEADER_VALUE=practice-key
#   ACTION_API_USER_HEADER=X-User-Key
import csv
import os
import re
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

API_KEY = os.getenv("MOCK_API_KEY", "practice-key")
DATA_DIR = Path(__file__).parent / "server_data"


def read_csv(name):
    with open(DATA_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# 표의 한글 열 이름을 실제 API처럼 영어 이름으로 바꿔 둔다
PRODUCTS = [
    {
        "code": row["품목코드"], "village": row["마을"], "name": row["품목명"], "spec": row["규격"],
        "price": int(row["가격"]), "is_live": row["활어여부"] == "Y",
        "sale_start": row["판매시작"], "sale_end": row["판매종료"],
        "max_per_order": int(row["1회최대수량"]), "stock": int(row["재고"]), "note": row.get("비고", ""),
    }
    for row in read_csv("재고표.csv")
]
PRODUCT_BY_CODE = {p["code"]: p for p in PRODUCTS}
MEMBERS = read_csv("회원명부.csv")

# 대화 상대(X-User-Key)마다 재고와 주문을 따로 둔다 (시험을 여러 번 동시에 돌려도 서로 섞이지 않게)
sessions = {}
order_count = 0


def session(user_key):
    if user_key not in sessions:
        sessions[user_key] = {"stock": {p["code"]: p["stock"] for p in PRODUCTS}, "orders": []}
    return sessions[user_key]


def check_key(api_key):
    if api_key != API_KEY:
        raise HTTPException(401, "API 키가 올바르지 않습니다.")


app = FastAPI(title="연습용 액션 서버")


@app.get("/products")
def products(keyword: str = "", code: str = "", x_api_key: str = Header(""), x_user_key: str = Header("anonymous")):
    check_key(x_api_key)
    stock = session(x_user_key)["stock"]
    rows = [
        dict(p, stock=stock[p["code"]])
        for p in PRODUCTS
        if (not code or p["code"] == code) and (not keyword or keyword in p["name"])
    ]
    return {"products": rows}


@app.get("/members/grade")
def member_grade(name: str, phone: str, x_api_key: str = Header("")):
    check_key(x_api_key)
    # 이름과 연락처가 모두 맞아야 등급을 알려 준다 (명부 전체는 내주지 않는다)
    for member in MEMBERS:
        if member["이름"] == name and member["연락처"] == phone:
            return {"name": name, "grade": member["회원등급"]}
    return {"name": name, "grade": "일반"}


class Item(BaseModel):
    code: str
    qty: int
    amount: int


class OrderIn(BaseModel):
    customer_name: str
    phone: str
    address: str
    delivery_date: str
    payment: str
    items: list[Item]
    shipping_fee: int
    total: int


@app.post("/orders")
def create_order(order: OrderIn, x_api_key: str = Header(""), x_user_key: str = Header("anonymous")):
    global order_count
    check_key(x_api_key)
    state = session(x_user_key)
    # 서버 쪽 기본 검사 (진짜 액션 서버도 이런 식으로 거절할 수 있다)
    if not re.fullmatch(r"010-\d{4}-\d{4}", order.phone):
        raise HTTPException(400, "연락처는 010-0000-0000 형식이어야 합니다.")
    if order.payment not in ("선불", "후불"):
        raise HTTPException(400, "payment는 선불 또는 후불이어야 합니다.")
    if not order.items:
        raise HTTPException(400, "items가 비었습니다.")
    for item in order.items:
        product = PRODUCT_BY_CODE.get(item.code)
        if not product:
            raise HTTPException(400, f"없는 품목코드입니다: {item.code}")
        if not 1 <= item.qty <= product["max_per_order"]:
            raise HTTPException(400, f"{item.code} 수량은 1~{product['max_per_order']}이어야 합니다.")
        if item.qty > state["stock"][item.code]:
            raise HTTPException(400, f"{item.code} 재고가 부족합니다 (남은 재고 {state['stock'][item.code]}).")

    for item in order.items:
        state["stock"][item.code] -= item.qty
    order_count += 1
    record = {"order_id": f"ORD-{order_count:04d}", "status": "접수", **order.model_dump()}
    state["orders"].append(record)
    return record


@app.get("/orders")
def my_orders(x_api_key: str = Header(""), x_user_key: str = Header("anonymous")):
    check_key(x_api_key)
    return {"orders": session(x_user_key)["orders"]}


@app.post("/orders/{order_id}/cancel")
def cancel_order(order_id: str, x_api_key: str = Header(""), x_user_key: str = Header("anonymous")):
    check_key(x_api_key)
    state = session(x_user_key)
    for record in state["orders"]:
        if record["order_id"] == order_id:
            if record["status"] == "취소":
                raise HTTPException(400, "이미 취소된 주문입니다.")
            record["status"] = "취소"
            for item in record["items"]:
                state["stock"][item["code"]] += item["qty"]
            return record
    raise HTTPException(404, f"주문을 찾을 수 없습니다: {order_id}")
