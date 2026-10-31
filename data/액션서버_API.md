# 액션 API 목록 (call_action_api로 호출)
조회: 단건이 없으면 404, 검색 결과가 없으면 []. 경로·파라미터가 틀려도 본문 없는 404·400이 오니 대상이 없다고 단정하기 전에 경로를 확인한다.
접수: 접수 API는 요청을 기록만 하고 정책을 검사하지 않는다. 어긋나는 요청도 그대로 접수되므로 호출 전에 규정을 확인한다. 같은 대상에 다시 접수하면 같은 접수번호가 돌아오고 내용이 덮어써진다.

## 상품·로트·재고
API-01 GET /api/products/{sku} 상품 조회 (price는 현재 판매가)
API-02 GET /api/products?item=품목접두사 품목별 상품 검색 (WTM 수박, HGL 하우스감귤, NGL 노지감귤, MDR 만감류, MNG 애플망고, MLN 멜론, PTT 감자, SWP 고구마, KIW 참다래, SLC 절임배추, OKD 옥돔, GAL 갈치)
API-03 GET /api/lots/{lot_id} 로트 조회 (packed_at, measured_weight_g, measured_brix, grade, status, sprayed_at)
API-04 GET /api/lots/{lot_id}/investigation 로트 조사 조회 (없으면 404 = 조사 기록 없음)
API-21 GET /api/inventory?sku= 재고 조회
API-39 POST /api/products/{sku}/restock-notification-requests 재입고 알림 등록 (본문 없음)

## 주문
API-07 GET /api/orders/{order_no} 주문 조회 (member_id, status, amount, items, payment_refs, inflow_tag, ship_scheduled_at)
API-08 GET /api/orders?member_id= 회원별 주문 검색
API-09 GET /api/orders?inflow_tag= 유입태그별 주문 검색
API-22 POST /api/orders/{order_no}/restore-requests 주문 복구 접수 (본문 없음)
API-23 POST /api/orders/{order_no}/change-requests 주문 변경 접수 {requested_items:[품목마다 "SKU 수량" 문자열]}
API-24 POST /api/orders/{order_no}/address-change-requests 배송지 변경 접수 {new_address}
API-25 POST /api/orders/{order_no}/schedule-change-requests 배송 일정 변경 접수 {requested_date:"YYYY-MM-DD"}
API-26 POST /api/orders/{order_no}/memos 주문 메모 접수 {memo}
API-27 POST /api/orders/{order_no}/expedite-requests 긴급 출고 접수 {qty, reason}
API-38 POST /api/orders/{order_no}/pickup-requests 픽업(회수) 접수 {qty, trigger, cost_bearer:SELLER|CUSTOMER}

## 배송·구독
API-10 GET /api/shipments/{shipment_id} 배송 조회
API-11 GET /api/shipments?order_no= 주문별 배송 검색 (status READY|IN_TRANSIT|DELIVERED|RETURNED, picked_up_at, delivered_at, items의 lot_id). 결과가 []이면 아직 배송 건이 없는 집하 전 상태다
API-28 POST /api/shipments/{shipment_id}/reship-requests 재배송 접수 (본문 없음)
API-37 POST /api/shipments/{shipment_id}/reship-charge-requests 재배송비 청구 접수 {charge_amount}
API-19 GET /api/subscriptions/{subscription_id} 구독 조회
API-40 POST /api/subscriptions/{subscription_id}/change-requests 구독 변경 접수 {kind:SKIP|CANCEL}

## 결제·환불
API-17 GET /api/payments/{approval_no} 결제 조회 (pay_method, amount, status)
API-18 GET /api/payments?order_no= 주문별 결제 검색
API-29 POST /api/refunds 환불 신청 {order_no, amount, reason}
API-30 GET /api/refunds?order_no= 주문별 환불 검색
API-31 POST /api/payments/{approval_no}/cancellation-requests 카드 취소 접수 (본문 없음)
API-32 POST /api/payments/{approval_no}/cash-receipt-requests 현금영수증 발행 접수 {receipt_number}

## 조합원·쿠폰·프로모션·상담 이력
API-12 GET /api/members/{member_id} 조합원 조회
API-13 GET /api/members?name= 이름 조합원 검색 (정확히 일치)
API-14 GET /api/members?referred_by= 추천인별 조합원 검색
API-15 GET /api/point-entries?member_id= 적립금 내역 검색
API-16 GET /api/coupons?member_id= 회원별 쿠폰 검색
API-20 GET /api/promos/{code} 프로모션 조회 (benefit_type, benefit_value, valid_from, valid_until, target_skus, stackable_with)
API-33 POST /api/members/{member_id}/coupon-issue-requests 쿠폰 발급 접수 {promo_code}
API-34 POST /api/members/{member_id}/reward-requests 리워드 지급 접수 (본문 없음)
API-05 GET /api/tickets?member_id= 회원별 상담 이력 검색
API-06 GET /api/tickets?lot_id= 로트별 상담 이력 검색

## 이관
API-35 POST /api/escalations 에스컬레이션 {lane, reason} (응답의 escalation_id가 이관 접수번호)
API-36 GET /api/escalations/{escalation_id} 에스컬레이션 조회
