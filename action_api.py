# 운영진 액션 서버(API)를 부르는 공통 함수
# 서버 .env에 넣는 값
#   ACTION_API_BASE_URL     액션 서버 주소 — 비어 있으면 액션 서버를 안 쓴다
#   ACTION_API_HEADER_NAME  인증 헤더 이름 (Authorization)
#   ACTION_API_HEADER_VALUE 인증 헤더 값   (Bearer aitop100_...)
# 케이스 ID(TC ID)는 대화에서 받은 값을 memory에서 꺼내 X-Aitop100-Test-Case-Id 헤더로 붙인다
import logging
import os
import time

import httpx

import memory

log = logging.getLogger("bot")

BASE_URL = os.getenv("ACTION_API_BASE_URL", "").rstrip("/")
HEADER_NAME = os.getenv("ACTION_API_HEADER_NAME", "")
HEADER_VALUE = os.getenv("ACTION_API_HEADER_VALUE", "")
CASE_HEADER = "X-Aitop100-Test-Case-Id"
TIMEOUT = float(os.getenv("ACTION_API_TIMEOUT", "8"))
ALLOWED_METHODS = {"GET", "POST"}
# 일시적인 오류면 한 번만 다시 보낸다 (접수 API는 다시 보내도 같은 접수번호가 돌아온다)
RETRY_STATUS = {429, 500, 503}
MAX_RETRY_WAIT = 3

# 커넥션을 재사용해서 호출마다 TLS 연결을 새로 맺는 시간을 줄인다
client = httpx.Client(timeout=TIMEOUT)


def enabled():
    return bool(BASE_URL)


def send(method, url, query, body, headers):
    try:
        response = client.request(method, url, params=query or None, json=body, headers=headers)
    except httpx.TransportError as e:
        # 재사용하던 연결이 끊긴 경우가 있어 한 번 더 보낸다 (접수 API는 다시 보내도 같은 접수번호가 돌아온다)
        log.warning("액션 서버 연결 재시도: %s", e.__class__.__name__)
        response = client.request(method, url, params=query or None, json=body, headers=headers)
    if response.status_code in RETRY_STATUS:
        wait = min(float(response.headers.get("Retry-After", "1") or 1), MAX_RETRY_WAIT)
        log.warning("액션 서버 %d → %.0f초 뒤 다시 시도", response.status_code, wait)
        time.sleep(wait)
        response = client.request(method, url, params=query or None, json=body, headers=headers)
    return response


def call(method, path, user_key, query=None, body=None, case_id=""):
    # 결과는 {"상태코드": 200, "응답": ...} 모양으로 돌려준다
    # 실패해도 에러를 결과로 돌려줘서 LLM이 읽고 대처(고쳐서 다시 시도, 고객에게 안내)할 수 있게 한다
    method = str(method).upper()
    path = "/" + str(path).lstrip("/")
    if not BASE_URL:
        return {"오류": "액션 서버 주소(ACTION_API_BASE_URL)가 설정되지 않았습니다."}
    if method not in ALLOWED_METHODS:
        return {"오류": f"쓸 수 없는 방식입니다: {method}"}
    # 정해 둔 액션 서버 밖의 주소는 부르지 못하게 막는다 (프롬프트 인젝션으로 다른 서버를 부르게 하는 공격 방지)
    if "://" in path or ".." in path or not path.startswith("/api/"):
        return {"오류": "경로는 /api/로 시작하는 액션 서버 안의 주소만 쓸 수 있습니다."}
    # 데이터 초기화는 상담 중에 쓰는 기능이 아니다
    if path.startswith("/api/action-data"):
        return {"오류": "쓸 수 없는 경로입니다."}

    headers = {}
    if HEADER_NAME:
        headers[HEADER_NAME] = HEADER_VALUE
    # 코드가 대화에서 찾은 케이스 ID를 먼저 쓰고, 없으면 LLM이 읽어 넘긴 값을 쓴다
    case = memory.get_case(user_key) or str(case_id or "").strip()
    if case:
        headers[CASE_HEADER] = case

    payload = body if body is not None else ({} if method == "POST" else None)
    started = time.time()
    try:
        response = send(method, BASE_URL + path, query, payload, headers)
    except httpx.HTTPError as e:
        log.error("액션 서버 연결 실패 %s %s: %s", method, path, e)
        return {"오류": f"액션 서버에 연결하지 못했습니다: {e.__class__.__name__}"}
    log.info("액션 서버 %s %s → %d (%.1f초)", method, path, response.status_code, time.time() - started)

    try:
        data = response.json()
    except ValueError:
        data = response.text[:2000]
    result = {"상태코드": response.status_code, "응답": data}
    # 목록 검색 뒤에는 대상 주문을 단건으로 조회해야 금액·결제 정보를 정확히 쓸 수 있다
    if path == "/api/orders" and response.status_code == 200:
        result["안내"] = "대상 주문을 특정했으면 /api/orders/{order_no}로 그 주문을 조회한 뒤 처리한다."
    if response.status_code == 404:
        result["안내"] = "해당 대상이 없습니다(또는 경로가 틀렸습니다)."
    elif response.status_code == 400 and not data:
        result["안내"] = "요청 값이나 파라미터가 형식에 맞지 않습니다. API 문서와 비교해 고치세요."
    elif response.status_code >= 400:
        result["오류"] = "액션 서버가 요청을 거절했습니다."
    return result
