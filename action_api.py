# 운영진 액션 서버(API)를 부르는 공통 함수
# 대회 당일 문제 페이지에 나오는 주소와 인증 방식을 서버 .env에 넣으면 된다
#   ACTION_API_BASE_URL     액션 서버 주소 (예: https://action.example.com) — 비어 있으면 액션 서버를 안 쓴다
#   ACTION_API_HEADER_NAME  인증 헤더 이름 (예: Authorization 또는 X-API-Key)
#   ACTION_API_HEADER_VALUE 인증 헤더 값   (예: Bearer abc123 또는 abc123)
#   ACTION_API_USER_HEADER  대화 상대 구분값을 보내라고 하면 그 헤더 이름 (예: X-User-Key)
import logging
import os
import time

import httpx

log = logging.getLogger("bot")

BASE_URL = os.getenv("ACTION_API_BASE_URL", "").rstrip("/")
HEADER_NAME = os.getenv("ACTION_API_HEADER_NAME", "")
HEADER_VALUE = os.getenv("ACTION_API_HEADER_VALUE", "")
USER_HEADER = os.getenv("ACTION_API_USER_HEADER", "")
TIMEOUT = float(os.getenv("ACTION_API_TIMEOUT", "15"))
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def enabled():
    return bool(BASE_URL)


def call(method, path, user_key, query=None, body=None):
    # 결과는 {"상태코드": 200, "응답": ...} 모양으로 돌려준다
    # 실패해도 에러를 결과로 돌려줘서 LLM이 읽고 대처(고쳐서 다시 시도, 고객에게 안내)할 수 있게 한다
    method = str(method).upper()
    path = "/" + str(path).lstrip("/")
    if not BASE_URL:
        return {"오류": "액션 서버 주소(ACTION_API_BASE_URL)가 설정되지 않았습니다."}
    if method not in ALLOWED_METHODS:
        return {"오류": f"쓸 수 없는 방식입니다: {method}"}
    # 정해 둔 액션 서버 밖의 주소는 부르지 못하게 막는다 (프롬프트 인젝션으로 다른 서버를 부르게 하는 공격 방지)
    if "://" in path or ".." in path:
        return {"오류": "경로는 /로 시작하는 액션 서버 안의 주소만 쓸 수 있습니다."}

    headers = {}
    if HEADER_NAME:
        headers[HEADER_NAME] = HEADER_VALUE
    if USER_HEADER:
        headers[USER_HEADER] = user_key

    started = time.time()
    try:
        response = httpx.request(
            method, BASE_URL + path, params=query or None, json=body, headers=headers, timeout=TIMEOUT
        )
    except httpx.HTTPError as e:
        log.error("액션 서버 연결 실패 %s %s: %s", method, path, e)
        return {"오류": f"액션 서버에 연결하지 못했습니다: {e.__class__.__name__}"}
    log.info("액션 서버 %s %s → %d (%.1f초)", method, path, response.status_code, time.time() - started)

    try:
        data = response.json()
    except ValueError:
        data = response.text[:2000]
    result = {"상태코드": response.status_code, "응답": data}
    if response.status_code >= 400:
        result["오류"] = "액션 서버가 요청을 거절했습니다. 응답 내용을 읽고 고쳐서 다시 시도하거나 고객에게 안내하세요."
    return result
