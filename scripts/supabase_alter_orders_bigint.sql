-- 22003 "value ... is out of range for type integer" 대응 (orders)
-- Supabase Dashboard → SQL Editor → New query 에서 실행하세요.
-- 주문/상품/옵션 ID가 21억(2^31-1) 초과 시 INTEGER → BIGINT 로 변경해야 합니다.

-- 1) 먼저 아래 블록 실행 (public 스키마)
ALTER TABLE public.orders ALTER COLUMN shipment_box_id TYPE BIGINT;
ALTER TABLE public.orders ALTER COLUMN order_id TYPE BIGINT;
ALTER TABLE public.orders ALTER COLUMN vendor_item_id TYPE BIGINT;
ALTER TABLE public.orders ALTER COLUMN product_id TYPE BIGINT;
ALTER TABLE public.orders ALTER COLUMN seller_product_id TYPE BIGINT;

-- 2) "relation \"public.orders\" does not exist" 나오면 위 5줄 지우고 아래 5줄만 실행 (api 스키마)
-- ALTER TABLE api.orders ALTER COLUMN shipment_box_id TYPE BIGINT;
-- ALTER TABLE api.orders ALTER COLUMN order_id TYPE BIGINT;
-- ALTER TABLE api.orders ALTER COLUMN vendor_item_id TYPE BIGINT;
-- ALTER TABLE api.orders ALTER COLUMN product_id TYPE BIGINT;
-- ALTER TABLE api.orders ALTER COLUMN seller_product_id TYPE BIGINT;
