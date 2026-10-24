# 액션 서버 API 문서 (연습용)

call_action_api 도구로 method, path, query, body를 정해서 부른다. 인증 정보는 시스템이 자동으로 붙인다.

## 1. 상품 조회
GET /products
- query: keyword (상품명 일부, 선택), code (품목코드, 선택)
- 응답 예: {"products": [{"code": "A01", "village": "교동", "name": "사과(부사)", "spec": "10kg", "price": 35000, "is_live": false, "sale_start": "연중", "sale_end": "연중", "max_per_order": 10, "stock": 12, "note": ""}]}
- stock은 지금 남은 재고다. is_live가 true면 활어다.
- sale_start, sale_end가 "MM-DD"면 그 기간(양 끝 포함)에만 판매한다. "연중"은 언제나 판매한다.

## 2. 회원 등급 확인
GET /members/grade
- query: name (필수), phone (필수)
- 응답 예: {"name": "남궁민", "grade": "단골"} — 명부에 없으면 grade는 "일반"

## 3. 주문 등록
POST /orders
- body 예:
  {"customer_name": "홍길동", "phone": "010-0000-0000", "address": "서울 ...", "delivery_date": "2026-11-06",
   "payment": "선불", "items": [{"code": "A01", "qty": 2, "amount": 70000}], "shipping_fee": 0, "total": 70000}
- payment는 "선불" 또는 "후불". amount는 그 품목의 price × qty, shipping_fee는 상담규정의 배송비 합계, total은 상품금액 합계 + 배송비.
- 응답: 등록된 주문 (order_id, status "접수" 포함)
- 거절(상태코드 400): 없는 품목코드, 수량 범위 밖, 재고 부족, 연락처 형식 오류 — 응답의 detail에 이유가 있다.

## 4. 내 주문 목록
GET /orders
- 응답: {"orders": [ ...등록한 주문들... ]}

## 5. 주문 취소
POST /orders/{order_id}/cancel
- 응답: 취소된 주문 (status "취소"). 취소하면 재고가 돌아온다.
