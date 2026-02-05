# Dashboard

**마지막 업데이트:** 2026-02-05 22:00

---

## 전체 진행률

| Phase | 내용 | 상태 | 완료율 |
|-------|------|------|--------|
| **Phase 1** | 데이터 수집 + 마진 분석 + CSV 생성 | ✅ 완료 | 100% |
| **Phase 2** | 쿠팡 WING API 연동 + 자동 업로드 | ⏳ 진행중 | 95% |
| **Phase 3** | 판매 분석 엔진 + 대시보드 | ⏳ 진행중 | 80% |
| **Phase 4** | 가격 모니터링 + 알림 + 고도화 | ⏳ 대기 | 0% |

**현재 위치: Phase 2 거의 완료 (파이프라인 API 통합만 잔여) / Phase 3 대시보드 v3.2 운영중**

---

## Phase 2 상세 진행률

| Step | 내용 | 상태 |
|------|------|------|
| **Step 1** | WING API 클라이언트 + 5계정 상품 동기화 | ✅ 완료 (15,363개 동기화) |
| **Step 2-1** | 출고지/반품지 코드 조회 + DB 저장 | ✅ 완료 (5계정 모두) |
| **Step 2-2** | 도서 카테고리 코드 확인 | ✅ 완료 (동적 추천 적용) |
| **Step 2-3** | API 상품 등록 테스트 | ✅ 완료 (2개 상품 등록 성공) |
| **Step 2-4** | 파이프라인에 API 업로드 통합 | ⏳ 진행 예정 |
| **Step 3** | 매출 조회 + 매출 동기화 | ✅ 완료 (sync_revenue.py) |

---

## Phase 3 상세 진행률

| Step | 내용 | 상태 |
|------|------|------|
| **Step 1** | Streamlit 대시보드 v3.2 | ✅ 완료 (Tailscale HTTPS 배포) |
| **Step 2** | 매출 분석 UI (KPI + 인사이트) | ✅ 완료 (대시보드 탭 2개) |
| **Step 3** | 일일 자동 크롤링 스케줄러 | ✅ 완료 (매일 03:00 실행) |
| **Step 4** | 프랜차이즈 동기화 | ✅ 완료 (franchise_sync.py) |
| **Step 5** | 고급 분석 (트렌드, 예측) | ❌ 미구현 |

---

## 기능별 완료 상태

| 기능               | 코드  | 테스트 | 비고                            |
| ---------------- | :-: | :-: | ----------------------------- |
| DB 스키마 (9 테이블)   |  ✅  |  ✅  | `app/models/` (revenue_history 추가) |
| 알라딘 API 크롤러      |  ✅  |  ✅  | 2,535개 도서 수집                    |
| 연도 추출            |  ✅  |  ✅  | 87% 성공률                       |
| 마진 계산기           |  ✅  |  ✅  | 배송정책 자동 결정                    |
| 묶음 SKU 생성기       |  ✅  |  ✅  | 시리즈+연도 그룹화                    |
| 쿠팡 CSV 생성 (V4.5) |  ✅  |  ✅  | 113컬럼                         |
| 5계정 분산 업로드       |  ✅  |  ✅  | 중복 방지                         |
| 파이프라인 자동화        |  ✅  |  ✅  | `run_pipeline.py` 6단계         |
| Obsidian 자동 로깅   |  ✅  |  ✅  | 글로벌 훅 시스템으로 전환               |
| WING API 클라이언트   |  ✅  |  ✅  | HMAC 인증, 전 엔드포인트              |
| WING API 상품 동기화  |  ✅  |  ✅  | 5계정 15,363개 동기화               |
| 출고지/반품지 코드 조회    |  ✅  |  ✅  | 5계정 DB 저장 완료                  |
| 카테고리 추천          |  ✅  |  ✅  | 동적 추천 + 캐시                    |
| API 상품 등록        |  ✅  |  ✅  | 2개 상품 등록 성공                   |
| **프랜차이즈 동기화**    |  ✅  |  ✅  | `franchise_sync.py` 55개 출판사   |
| **매출 동기화**       |  ✅  |  ✅  | `sync_revenue.py` 962건        |
| **Streamlit 대시보드** |  ✅  |  ✅  | **v3.2** Tailscale HTTPS 배포  |
| **자동 크롤링 스케줄러**  |  ✅  |  ✅  | `auto_crawl.py` 매일 03:00      |
| 파이프라인 API 통합     |  ⏳  |  ❌  | Phase 2 잔여 (CSV→API 전환)       |
| 가격 모니터링          |  ❌  |  ❌  | Phase 4                       |
| 알림 시스템           |  ❌  |  ❌  | Phase 4                       |

---

## WING API 5계정 현황

| 계정 | vendor_id | 상품수 | 출고지 | 반품지 | API 등록 |
|------|-----------|--------|--------|--------|----------|
| 007-book | A01105984 | 2,990 | 24105055 | 1002509459 | ✅ 테스트 완료 |
| 007-bm | A00317195 | 3,089 | 3818765 | 1002504253 | ✅ 준비 완료 |
| 007-ez | A01234216 | 3,294 | 21009623 | 1002504172 | ✅ 준비 완료 |
| 002-bm | A01163064 | 2,623 | 20884668 | 1002504202 | ✅ 준비 완료 |
| big6ceo | A01258837 | 3,367 | 21307952 | 1002514534 | ✅ 준비 완료 |

**API 키 만료:** 2026.08.04 (약 180일 남음)

---

## 구현 파일 맵

| 기능         | 파일                                   | 핵심 클래스/메서드                                      |
| ---------- | ------------------------------------ | ----------------------------------------------- |
| DB 모델      | `app/models/*.py`                    | Book, Publisher, Product, BundleSKU, Listing, RevenueHistory |
| 출판사 설정     | `config/publishers.py`               | 55개 출판사 매입율/공급률                                 |
| 알라딘 크롤링    | `crawlers/aladin_api_crawler.py`     | `AladinAPICrawler.search_by_keyword()`          |
| 마진 분석      | `analyzers/margin_calculator.py`     | `MarginCalculator.analyze_book()`               |
| 묶음 생성      | `analyzers/bundle_generator.py`      | `BundleGenerator.auto_generate_bundles()`       |
| CSV 생성     | `uploaders/coupang_csv_generator.py` | `CoupangCSVGenerator.generate_csv()`            |
| 파이프라인      | `scripts/run_pipeline.py`            | 6단계 자동화                                         |
| WING 클라이언트 | `app/api/coupang_wing_client.py`     | `CoupangWingClient` (HMAC 인증)                   |
| 상품 동기화     | `scripts/sync_coupang_products.py`   | `sync_account_products()`                       |
| 출고지/반품지    | `scripts/setup_shipping_places.py`   | `query_shipping_places()`                       |
| API 등록     | `uploaders/coupang_api_uploader.py`  | `CoupangAPIUploader.upload_product()`           |
| API 등록 테스트 | `scripts/test_api_upload.py`         | `run_test()`                                    |
| 비즈니스 상수    | `app/constants.py`                   | `BOOK_PRODUCT_DEFAULTS`, `WING_ACCOUNT_ENV_MAP` |
| **대시보드**   | `dashboard.py`                       | Streamlit v3.2 (KPI + 매출분석 + 인사이트)              |
| **매출 동기화** | `scripts/sync_revenue.py`            | `RevenueSync` 클래스                               |
| **자동 크롤링** | `scripts/auto_crawl.py`             | 매일 03:00 스케줄러 (schedule 라이브러리)                  |
| **프랜차이즈**  | `scripts/franchise_sync.py`          | `FranchiseSync.crawl_by_publisher()`            |
| **매출 모델**  | `app/models/revenue_history.py`      | `RevenueHistory` SQLAlchemy 모델                   |

---

## 데이터 현황 (DB 실측)

| 항목 | 수량 |
|------|------|
| 출판사 | 55개 |
| 수집 도서 | 2,535개 |
| 상품 | 2,535개 |
| 쿠팡 계정 | 5개 |
| DB Listings 총계 | 15,363개 |
| 매출 기록 | 962건 |
| API 등록 테스트 | 2개 성공 |

---

## 다음 할 일 (우선순위)

1. ~~WING API 클라이언트~~ ✅
2. ~~5계정 상품 동기화~~ ✅ (15,363개)
3. ~~출고지/반품지 코드 조회~~ ✅
4. ~~카테고리 코드 확인~~ ✅ (동적 추천)
5. ~~API 상품 등록 테스트~~ ✅ (2개 성공)
6. ~~매출 동기화~~ ✅ (sync_revenue.py, 962건)
7. ~~Streamlit 대시보드~~ ✅ (v3.2 배포 완료)
8. ~~자동 크롤링 스케줄러~~ ✅ (매일 03:00)
9. **파이프라인 API 업로드 통합** - CSV 대신 API 등록으로 전환
10. **재고/가격 실시간 관리** - `update_inventory()` 활용
11. **가격 모니터링 + 알림** - Phase 4

---

## 운영 환경

| 항목 | 설정 |
|------|------|
| 대시보드 URL | `https://desktop-gg1evvh.tail25da99.ts.net` |
| 대시보드 포트 | 8503 |
| 자동 크롤링 | 매일 03:00 (start_auto_crawl.vbs) |
| 대시보드 자동시작 | start_dashboard_hidden.vbs (Startup 폴더) |

---

## 관련 문서

- [[Index]] - 전체 문서 목차
- [[Development-Timeline]] - 개발 타임라인
- [[쿠팡-API-연동]] - WING API 상세 문서
- [[매출-분석-대시보드]] - 대시보드 v3.2 기능 문서
- [[자동-크롤링-스케줄러]] - 자동 크롤링 기능 문서
- [[프랜차이즈-동기화]] - 프랜차이즈 동기화 문서
- [[대시보드-접속-가이드]] - Tailscale 배포 가이드
