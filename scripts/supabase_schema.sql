-- Coupong Supabase PostgreSQL Schema
-- Supabase Dashboard → SQL Editor에서 실행하세요

-- 1. 기본 테이블 (FK 없음)
CREATE TABLE IF NOT EXISTS accounts (
    id SERIAL PRIMARY KEY,
    account_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    password_encrypted VARCHAR(500) NOT NULL,
    session_file VARCHAR(255),
    is_active BOOLEAN DEFAULT true,
    last_login_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    vendor_id VARCHAR(20),
    wing_access_key VARCHAR(100),
    wing_secret_key VARCHAR(100),
    wing_api_enabled BOOLEAN DEFAULT false,
    outbound_shipping_code VARCHAR(50),
    return_center_code VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS publishers (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    margin_rate INTEGER NOT NULL,
    min_free_shipping INTEGER NOT NULL,
    supply_rate FLOAT NOT NULL,
    is_active BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    task_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending',
    params JSON,
    result JSON,
    error_message TEXT,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 2. FK → accounts
CREATE TABLE IF NOT EXISTS ad_spends (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    ad_date DATE NOT NULL,
    campaign_id VARCHAR(50) NOT NULL,
    campaign_name VARCHAR(200),
    ad_type VARCHAR(20),
    ad_objective VARCHAR(50),
    daily_budget INTEGER,
    spent_amount INTEGER,
    adjustment INTEGER,
    spent_after_adjust INTEGER,
    over_spend INTEGER,
    billable_cost INTEGER,
    vat_amount INTEGER,
    total_charge INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_account_date_campaign UNIQUE (account_id, ad_date, campaign_id)
);

CREATE TABLE IF NOT EXISTS settlement_history (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    year_month VARCHAR(7) NOT NULL,
    settlement_type VARCHAR(20),
    settlement_date VARCHAR(10),
    settlement_status VARCHAR(20),
    revenue_date_from VARCHAR(10),
    revenue_date_to VARCHAR(10),
    total_sale INTEGER,
    service_fee INTEGER,
    settlement_target_amount INTEGER,
    settlement_amount INTEGER,
    last_amount INTEGER,
    pending_released_amount INTEGER,
    seller_discount_coupon INTEGER,
    downloadable_coupon INTEGER,
    seller_service_fee INTEGER,
    courantee_fee INTEGER,
    deduction_amount INTEGER,
    debt_of_last_week INTEGER,
    final_amount INTEGER,
    bank_name VARCHAR(50),
    bank_account VARCHAR(50),
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_account_month_type_date UNIQUE (account_id, year_month, settlement_type, settlement_date)
);

-- 3. FK → publishers
CREATE TABLE IF NOT EXISTS books (
    id SERIAL PRIMARY KEY,
    isbn VARCHAR(13) NOT NULL UNIQUE,
    title VARCHAR(500) NOT NULL,
    author VARCHAR(200),
    publisher_id INTEGER REFERENCES publishers(id),
    publisher_name VARCHAR(100),
    list_price INTEGER NOT NULL,
    category VARCHAR(100),
    subcategory VARCHAR(100),
    year INTEGER,
    normalized_title VARCHAR(500),
    normalized_series VARCHAR(200),
    image_url TEXT,
    description TEXT,
    source_url TEXT,
    publish_date DATE,
    page_count INTEGER,
    sales_point INTEGER DEFAULT 0,
    is_processed BOOLEAN DEFAULT false,
    crawled_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bundle_skus (
    id SERIAL PRIMARY KEY,
    bundle_key VARCHAR(200) NOT NULL,
    bundle_name VARCHAR(300) NOT NULL,
    publisher_id INTEGER NOT NULL REFERENCES publishers(id),
    normalized_series VARCHAR(200) NOT NULL,
    year INTEGER NOT NULL,
    book_count INTEGER NOT NULL,
    book_ids TEXT NOT NULL,
    isbns TEXT NOT NULL,
    total_list_price INTEGER NOT NULL,
    total_sale_price INTEGER NOT NULL,
    supply_rate FLOAT NOT NULL,
    total_margin INTEGER NOT NULL,
    shipping_cost INTEGER,
    net_margin INTEGER NOT NULL,
    shipping_policy VARCHAR(20),
    status VARCHAR(20) DEFAULT 'ready',
    created_at TIMESTAMP DEFAULT NOW()
);

-- 4. FK → books
CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id),
    isbn VARCHAR(13) NOT NULL,
    list_price INTEGER NOT NULL,
    sale_price INTEGER NOT NULL,
    supply_rate FLOAT NOT NULL,
    margin_per_unit INTEGER NOT NULL,
    shipping_cost INTEGER DEFAULT 2300,
    net_margin INTEGER NOT NULL,
    shipping_policy VARCHAR(20) NOT NULL,
    can_upload_single BOOLEAN DEFAULT true,
    status VARCHAR(20) DEFAULT 'ready',
    exclude_reason TEXT,
    registration_status VARCHAR(20) DEFAULT 'pending_review',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 5. FK → accounts, products, bundle_skus
CREATE TABLE IF NOT EXISTS listings (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    product_type VARCHAR(50) NOT NULL,
    product_id INTEGER REFERENCES products(id),
    bundle_id INTEGER REFERENCES bundle_skus(id),
    isbn VARCHAR(100),
    bundle_key VARCHAR(200),
    coupang_product_id VARCHAR(50),
    coupang_status VARCHAR(50) DEFAULT 'pending',
    product_name VARCHAR(500),
    original_price INTEGER DEFAULT 0,
    sale_price INTEGER NOT NULL,
    shipping_policy VARCHAR(50) NOT NULL,
    vendor_item_id VARCHAR(50),
    coupang_sale_price INTEGER DEFAULT 0,
    stock_quantity INTEGER DEFAULT 10,
    brand VARCHAR(200),
    display_category_code VARCHAR(50),
    delivery_charge_type VARCHAR(50),
    maximum_buy_count INTEGER,
    supply_price INTEGER,
    delivery_charge INTEGER,
    free_ship_over_amount INTEGER,
    return_charge INTEGER,
    winner_status VARCHAR(50),
    winner_checked_at TIMESTAMP,
    item_id VARCHAR(50),
    raw_json TEXT,
    detail_synced_at TIMESTAMP,
    upload_method VARCHAR(50),
    uploaded_at TIMESTAMP DEFAULT NOW(),
    last_checked_at TIMESTAMP,
    error_message TEXT,
    CONSTRAINT uix_account_isbn UNIQUE (account_id, isbn),
    CONSTRAINT uix_account_bundle UNIQUE (account_id, bundle_key)
);

-- 6. FK → listings
CREATE TABLE IF NOT EXISTS sales (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    date DATE NOT NULL,
    views INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    orders INTEGER DEFAULT 0,
    revenue INTEGER DEFAULT 0,
    refunds INTEGER DEFAULT 0,
    stock INTEGER DEFAULT 0,
    ranking INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_listing_date UNIQUE (listing_id, date)
);

CREATE TABLE IF NOT EXISTS analysis_results (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    analysis_date DATE NOT NULL,
    period_days INTEGER,
    total_views INTEGER DEFAULT 0,
    total_orders INTEGER DEFAULT 0,
    conversion_rate FLOAT,
    problem_type VARCHAR(50),
    priority_score FLOAT,
    recommended_actions JSON,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS inventory_sync_log (
    id SERIAL PRIMARY KEY,
    listing_id INTEGER NOT NULL REFERENCES listings(id),
    action VARCHAR(20) NOT NULL,
    old_price INTEGER,
    new_price INTEGER,
    old_quantity INTEGER,
    new_quantity INTEGER,
    success BOOLEAN DEFAULT true,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- 7. FK → accounts, listings
CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    shipment_box_id BIGINT NOT NULL,
    order_id BIGINT NOT NULL,
    vendor_item_id BIGINT,
    status VARCHAR(30),
    ordered_at TIMESTAMP,
    paid_at TIMESTAMP,
    orderer_name VARCHAR(100),
    receiver_name VARCHAR(100),
    receiver_addr VARCHAR(500),
    receiver_post_code VARCHAR(10),
    product_id BIGINT,
    seller_product_id BIGINT,
    seller_product_name VARCHAR(500),
    vendor_item_name VARCHAR(500),
    shipping_count INTEGER,
    cancel_count INTEGER,
    hold_count_for_cancel INTEGER,
    sales_price INTEGER,
    order_price INTEGER,
    discount_price INTEGER,
    shipping_price INTEGER,
    delivery_company_name VARCHAR(50),
    invoice_number VARCHAR(50),
    shipment_type VARCHAR(50),
    delivered_date TIMESTAMP,
    confirm_date TIMESTAMP,
    refer VARCHAR(50),
    canceled BOOLEAN DEFAULT false,
    listing_id INTEGER REFERENCES listings(id),
    raw_json TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_order_shipment_item UNIQUE (account_id, shipment_box_id, vendor_item_id)
);

CREATE TABLE IF NOT EXISTS return_requests (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    receipt_id BIGINT NOT NULL,
    order_id BIGINT,
    payment_id BIGINT,
    receipt_type VARCHAR(50),
    receipt_status VARCHAR(40),
    created_at_api TIMESTAMP,
    modified_at_api TIMESTAMP,
    requester_name VARCHAR(100),
    requester_phone VARCHAR(50),
    requester_address VARCHAR(500),
    requester_address_detail VARCHAR(200),
    requester_zip_code VARCHAR(10),
    cancel_reason_category1 VARCHAR(100),
    cancel_reason_category2 VARCHAR(100),
    cancel_reason TEXT,
    cancel_count_sum INTEGER,
    return_delivery_id BIGINT,
    return_delivery_type VARCHAR(50),
    release_stop_status VARCHAR(30),
    fault_by_type VARCHAR(50),
    pre_refund BOOLEAN DEFAULT false,
    complete_confirm_type VARCHAR(30),
    complete_confirm_date TIMESTAMP,
    reason_code VARCHAR(50),
    reason_code_text VARCHAR(200),
    return_shipping_charge INTEGER,
    enclose_price INTEGER,
    return_items_json TEXT,
    return_delivery_json TEXT,
    raw_json TEXT,
    listing_id INTEGER REFERENCES listings(id),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_return_account_receipt UNIQUE (account_id, receipt_id)
);

CREATE TABLE IF NOT EXISTS revenue_history (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    order_id BIGINT NOT NULL,
    sale_type VARCHAR(50) NOT NULL,
    sale_date DATE NOT NULL,
    recognition_date DATE NOT NULL,
    settlement_date DATE,
    product_id BIGINT,
    product_name VARCHAR(500),
    vendor_item_id BIGINT,
    vendor_item_name VARCHAR(500),
    sale_price INTEGER,
    quantity INTEGER,
    coupang_discount INTEGER,
    sale_amount INTEGER,
    seller_discount INTEGER,
    service_fee INTEGER,
    service_fee_vat INTEGER,
    service_fee_ratio FLOAT,
    settlement_amount INTEGER,
    delivery_fee_amount INTEGER,
    delivery_fee_settlement INTEGER,
    listing_id INTEGER REFERENCES listings(id),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_account_order_item UNIQUE (account_id, order_id, vendor_item_id)
);

CREATE TABLE IF NOT EXISTS ad_performances (
    id SERIAL PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    ad_date DATE NOT NULL,
    campaign_id VARCHAR(50),
    campaign_name VARCHAR(200),
    ad_group_name VARCHAR(200),
    coupang_product_id VARCHAR(50),
    product_name VARCHAR(500),
    listing_id INTEGER REFERENCES listings(id),
    keyword VARCHAR(200),
    match_type VARCHAR(20),
    impressions INTEGER DEFAULT 0,
    clicks INTEGER DEFAULT 0,
    ctr FLOAT,
    avg_cpc INTEGER,
    ad_spend INTEGER DEFAULT 0,
    direct_orders INTEGER DEFAULT 0,
    direct_revenue INTEGER DEFAULT 0,
    indirect_orders INTEGER DEFAULT 0,
    indirect_revenue INTEGER DEFAULT 0,
    total_orders INTEGER DEFAULT 0,
    total_revenue INTEGER DEFAULT 0,
    roas FLOAT,
    total_quantity INTEGER DEFAULT 0,
    direct_quantity INTEGER DEFAULT 0,
    indirect_quantity INTEGER DEFAULT 0,
    bid_type VARCHAR(30),
    sales_method VARCHAR(20),
    ad_type VARCHAR(50),
    option_id VARCHAR(50),
    ad_name VARCHAR(200),
    placement VARCHAR(100),
    creative_id VARCHAR(50),
    category VARCHAR(200),
    report_type VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uix_ad_perf_unique UNIQUE (account_id, ad_date, campaign_id, ad_group_name, coupang_product_id, keyword, report_type)
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn);
CREATE INDEX IF NOT EXISTS idx_books_publisher ON books(publisher_id);
CREATE INDEX IF NOT EXISTS idx_books_year ON books(year);
CREATE INDEX IF NOT EXISTS idx_products_book ON products(book_id);
CREATE INDEX IF NOT EXISTS idx_products_isbn ON products(isbn);
CREATE INDEX IF NOT EXISTS idx_products_status ON products(status);
CREATE INDEX IF NOT EXISTS idx_listings_account ON listings(account_id);
CREATE INDEX IF NOT EXISTS idx_listings_isbn ON listings(isbn);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(coupang_status);
CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id);
CREATE INDEX IF NOT EXISTS idx_revenue_account ON revenue_history(account_id);
CREATE INDEX IF NOT EXISTS idx_returns_account ON return_requests(account_id);
