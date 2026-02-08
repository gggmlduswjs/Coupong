-- 22001 "value too long for type character varying(20)" 대응
-- Supabase Dashboard → SQL Editor에서 이 파일 전체를 붙여넣고 한 번 실행하세요.
-- "relation ... does not exist" 나오면 public 대신 api 사용: 아래 모든 public. 을 api. 로 바꾼 뒤 다시 실행.

-- listings: VARCHAR(20) → VARCHAR(50)
ALTER TABLE public.listings ALTER COLUMN product_type TYPE VARCHAR(50);
ALTER TABLE public.listings ALTER COLUMN coupang_status TYPE VARCHAR(50);
ALTER TABLE public.listings ALTER COLUMN shipping_policy TYPE VARCHAR(50);
ALTER TABLE public.listings ALTER COLUMN display_category_code TYPE VARCHAR(50);
ALTER TABLE public.listings ALTER COLUMN delivery_charge_type TYPE VARCHAR(50);
ALTER TABLE public.listings ALTER COLUMN winner_status TYPE VARCHAR(50);
ALTER TABLE public.listings ALTER COLUMN upload_method TYPE VARCHAR(50);

-- orders: VARCHAR(20) → VARCHAR(50)
ALTER TABLE public.orders ALTER COLUMN shipment_type TYPE VARCHAR(50);

-- return_requests: VARCHAR(10)/(20) → VARCHAR(50)
ALTER TABLE public.return_requests ALTER COLUMN receipt_type TYPE VARCHAR(50);
ALTER TABLE public.return_requests ALTER COLUMN return_delivery_type TYPE VARCHAR(50);
ALTER TABLE public.return_requests ALTER COLUMN fault_by_type TYPE VARCHAR(50);

-- revenue_history: VARCHAR(10) → VARCHAR(50)
ALTER TABLE public.revenue_history ALTER COLUMN sale_type TYPE VARCHAR(50);
