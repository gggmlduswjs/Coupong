# 개발 타임라인

**마지막 업데이트:** 2026-02-05

---

## Phase 1: 데이터 수집 + 마진 분석 + CSV 생성 ✅ (100%)

**기간:** ~2026-02-05 완료

| 기능 | 상태 | 구현 파일 |
|------|:----:|-----------|
| DB V2 스키마 (8 테이블) | ✅ | `app/models/*.py` |
| 24개 출판사 설정 | ✅ | `config/publishers.py` |
| 알라딘 API 크롤링 | ✅ | `crawlers/aladin_api_crawler.py` |
| 연도 자동 추출 (87%) | ✅ | `app/models/book.py` |
| 마진 계산 + 배송정책 | ✅ | `analyzers/margin_calculator.py` |
| 묶음 SKU 자동 생성 | ✅ | `analyzers/bundle_generator.py` |
| 쿠팡 CSV V4.5 (113컬럼) | ✅ | `uploaders/coupang_csv_generator.py` |
| 5계정 분산 + 중복 방지 | ✅ | `scripts/run_pipeline.py` |
| 기존 상품 import | ✅ | `scripts/import_existing_products.py` |
| Obsidian 자동 로깅 | ✅ | `obsidian_logger.py`, `auto_logger.py` |

**성과:** 981개 도서 수집, 4,765개 등록, 38.5초 파이프라인

---

## Phase 2: 쿠팡 WING API 연동 + 자동 업로드 ⏳ (80%) ← 현재

**기간:** 2026-02-05 ~

### Step 1: WING API 클라이언트 + 5계정 상품 동기화 ✅

| 기능 | 상태 | 구현 파일 |
|------|:----:|-----------|
| HMAC-SHA256 인증 클라이언트 | ✅ | `app/api/coupang_wing_client.py` |
| 5계정 API 키 설정 (Account 모델 확장) | ✅ | `app/models/account.py` |
| 상품 목록 조회 (nextToken 페이징) | ✅ | `CoupangWingClient.list_products()` |
| 5계정 상품 동기화 (14,972개) | ✅ | `scripts/sync_coupang_products.py` |
| 비즈니스 상수 모듈화 | ✅ | `app/constants.py` |
| DB 마이그레이션 패턴 (ALTER TABLE) | ✅ | `_migrate_account_columns()` |

### Step 2: 출고지/반품지 + 카테고리 + API 상품 등록 ✅

| 기능                    | 상태  | 구현 파일                                     |
| --------------------- | :-: | ----------------------------------------- |
| 출고지/반품지 코드 조회 + DB 저장 |  ✅  | `scripts/setup_shipping_places.py`        |
| 카테고리 동적 추천 (캐시 포함)    |  ✅  | `CoupangAPIUploader.recommend_category()` |
| API 상품 등록 JSON 빌드     |  ✅  | `uploaders/coupang_api_uploader.py`       |
| 도서 고시정보 (서적, 7개 항목)   |  ✅  | `build_product_payload()`                 |
| 필수 속성 (학습과목/학년/ISBN)  |  ✅  | `build_product_payload()`                 |
| API 상품 등록 테스트 (2개 성공) |  ✅  | `scripts/test_api_upload.py`              |

### Step 3: 파이프라인 통합 + 대량 등록 ❌

| 기능 | 상태 | 설명 |
|------|:----:|------|
| 파이프라인에 API 업로드 통합 | ❌ | CSV 대신 API 등록으로 전환 |
| 일일 스케줄러 | ❌ | 매일 신간 검색 + API 자동 등록 |
| 대량 등록 (953개 단권) | ❌ | `upload_batch()` 활용 |
| 업로드 결과 추적 | ❌ | listing 상태 자동 업데이트 |

### Step 4: 발주서/매출 조회 + 재고 관리 ❌

| 기능 | 상태 | 설명 |
|------|:----:|------|
| 발주서 조회 API | ❌ | `get_ordersheets()` 활용 |
| 매출 데이터 수집 | ❌ | sales 테이블에 저장 |
| 재고/가격 실시간 관리 | ❌ | `update_inventory()` 활용 |

---

## Phase 3: 판매 분석 엔진 + 대시보드 (0%)

| 기능 | 상태 | 설명 |
|------|:----:|------|
| 판매 데이터 분석 | ❌ | WING API 발주서 데이터 기반 |
| 계정별 성과 분석 | ❌ | 판매액, 권수, 마진 |
| 출판사별 수익성 분석 | ❌ | ROI 계산 |
| Streamlit 대시보드 | ⏳ | `dashboard/` 디렉토리 생성됨 (기본 구조만) |

---

## Phase 4: 고도화 (0%)

| 기능 | 상태 | 설명 |
|------|:----:|------|
| 경쟁사 가격 모니터링 | ❌ | 자동 가격 조정 |
| 주간/월간 리포트 | ❌ | 자동 생성 |
| 알림 시스템 | ❌ | Telegram/Slack 연동 |
| 신간 자동 감지 | ❌ | 즉시 등록 |

---

## 주요 마일스톤

| 날짜 | 마일스톤 |
|------|----------|
| 2026-02-05 | Phase 1 완료 (981개 도서, 파이프라인, CSV) |
| 2026-02-05 | WING API 클라이언트 구현 + 14,972개 상품 동기화 |
| 2026-02-05 | 출고지/반품지 5계정 설정 완료 |
| 2026-02-05 | API 상품 등록 2개 성공 (007-book 계정) |

---

## 관련 문서

- [[Dashboard]] - 진행률 + 기능 완료 상태
- [[Index]] - 전체 문서 목차
- [[쿠팡-API-연동]] - WING API 상세 문서
