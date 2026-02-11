# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

쿠팡 도서 판매 자동화 시스템. 알라딘 API로 신간을 크롤링하고, 마진을 분석한 뒤, 개별/묶음 상품을 쿠팡에 등록하고, 판매 데이터를 동기화하여 대시보드로 관리한다.

- **파이프라인:** 알라딘 API → DB 저장 → 마진 분석 → 상품/묶음 생성 → 쿠팡 WING API 등록 → 판매 동기화 → 대시보드 분석
- **스택:** Python 3.10+, SQLAlchemy 2.0, FastAPI, Streamlit, Playwright
- **DB:** 로컬 SQLite (`coupang_auto.db`), 프로덕션 PostgreSQL (Supabase)
- **계정:** 5개 쿠팡 셀러 계정 (각각 WING API 자격증명 보유)

## 명령어

```bash
# 대시보드 실행
streamlit run dashboard.py

# FastAPI 서버
uvicorn app.main:app --reload

# 메인 파이프라인 (크롤→분석→등록)
python scripts/run_pipeline.py

# 자동 크롤링 데몬 (새벽 3시)
python scripts/auto_crawl.py

# 동기화 스크립트 (주문/재고/매출/정산/반품/광고)
python scripts/sync_orders.py
python scripts/sync_inventory.py
python scripts/sync_revenue.py

# 테스트
pytest tests/

# 포맷 / 린트
black .
flake8
mypy .

# DB 초기화
python scripts/init_db_v2_clean.py

# WING API 테스트
python scripts/test_wing_api.py
```

## 아키텍처

### 핵심 모듈

```
app/
  api/coupang_wing_client.py    # WING API 클라이언트 (HMAC-SHA256 인증, 0.1초 throttle)
  models/                       # SQLAlchemy ORM 모델 15개
    book.py                     #   알라딘 도서 데이터 (isbn, title, list_price, year)
    publisher.py                #   출판사 98개 (margin_rate 40-73%, supply_rate)
    product.py                  #   단일 상품 (book → 마진 분석 → 배송 정책)
    bundle_sku.py               #   묶음 상품 (같은 시리즈/출판사/연도 기준 그룹)
    account.py                  #   쿠팡 셀러 계정 5개
    listing.py                  #   계정별 상품 등록 (account × product/bundle)
    order.py                    #   주문 데이터 (WING API)
    sales.py, revenue_history.py, settlement_history.py
    ad_spend.py, ad_performance.py, return_request.py, analysis_result.py
  services/
    wing_sync_base.py           #   동기화 스크립트 공통 베이스 클래스
    exposure_strategy.py        #   노출 전략 엔진 (판매속도/광고효율/재고 스코어링)
    uploader_service.py         #   상품 등록 서비스
  constants.py                  #   비즈니스 상수 + 배송비 결정 함수
  config.py                     #   pydantic-settings 환경변수 설정
  database.py                   #   DB 연결 (SQLite/PostgreSQL 자동 분기)

crawlers/aladin_api_crawler.py  # 알라딘 TTB API 크롤러
analyzers/
  margin_calculator.py          # 마진 분석기
  bundle_generator.py           # 묶음 SKU 생성기
uploaders/
  coupang_api_uploader.py       # WING API 상품 등록
  coupang_csv_generator.py      # CSV 템플릿 v4.5 (113컬럼, 레거시)
config/publishers.py            # 출판사 98개 설정 (마진율, 공급률, 최소무료배송)
dashboard.py                    # Streamlit 대시보드 (매출/주문/정산/반품/노출전략/상품관리)
scripts/                        # 40+ 자동화 스크립트 (sync_*, update_*, fill_*, fix_*)
```

### 데이터 흐름

1. **크롤링:** `aladin_api_crawler.py` → `Book` 모델 (isbn, year, normalized_title 추출)
2. **마진 분석:** `Product.create_from_book(book, publisher)` — 판매가(정가×0.9) - 공급가 - 쿠팡수수료(11%) - 배송비
3. **묶음 생성:** 저마진 도서는 `bundle_generator.py`로 시리즈/출판사/연도 기준 묶음
4. **등록:** WING API (`coupang_api_uploader.py`) 또는 CSV (`coupang_csv_generator.py`)
5. **동기화:** `scripts/sync_*.py` 10개 스크립트로 주문/재고/매출/정산/반품/광고 동기화
6. **분석:** `exposure_strategy.py`로 판매속도·광고효율·재고 스코어링 → A-F 등급

### 비즈니스 규칙 (`app/constants.py`)

- **도서정가제:** 판매가 = 정가 × 0.9 (한국 법률)
- **쿠팡 수수료:** 판매가의 11%
- **배송비 결정:** `determine_customer_shipping_fee(margin_rate, list_price)` — 공급률+정가 조합으로 0/1000/2000/2300원 결정
- **안전잠금:** `PRICE_LOCK`, `DELETE_LOCK`, `SALE_STOP_LOCK`, `REGISTER_LOCK` — 스크립트 일괄 실행 차단, 대시보드 `dashboard_override=True`로만 해제
- **WING API 계정 매핑:** `WING_ACCOUNT_ENV_MAP` — 계정명 → 환경변수 prefix

### DB 관계

```
Publisher(1) → Book(N) → Product(N) → Listing(N) → Sales/Orders/Analysis
Publisher(1) → BundleSKU(N) → Listing(N)
Account(1) → Listing(N)
```

## 코드 규칙

- 한국어 주석
- UTF-8 인코딩 필수 (`encoding='utf-8'`)
- 기존 코드 스타일 따르기
- 환경변수: `.env` 파일 (`.env.example` 참고)

## Obsidian 자동 기록 (필수)

문서는 **Google Drive** `G:\내 드라이브\Obsidian\10. project\Coupong`에 있습니다.
**모든 기록(일일 로그, 기술 문서 등)은 G:에 직접 저장됩니다.** sync 불필요.
`.env`의 `OBSIDIAN_VAULT_PATH`로 경로 설정.

### 언제 기록하는가

- 코드 수정/생성/삭제 후
- 버그 수정 후
- 새 기능 구현 후
- 리팩토링 후
- 설정 변경 후
- 중요한 의사결정을 내린 후

### 기록 방법

**1. 일일 로그 (매 작업 후 필수)**

`G:/내 드라이브/Obsidian/10. project/Coupong/01-Daily/YYYY-MM-DD.md` 파일에 append:

```markdown
## HH:MM - 작업 제목

- **작업 내용**: 무엇을 했는지 간단 설명
- **변경 파일**: 수정한 파일 목록
- **이유**: 왜 이 변경을 했는지

---
```

파일이 없으면 아래 헤더로 새로 생성:
```markdown
# YYYY년 MM월 DD일 개발 로그

## 오늘의 작업

---
```

**2. 기능 노트 (새 기능 구현 시)**

`G:/내 드라이브/Obsidian/10. project/Coupong/02-Features/기능명.md`에 기능 문서 작성

**3. 기술 문서 (아키텍처 변경 시)**

`G:/내 드라이브/Obsidian/10. project/Coupong/03-Technical/문서명.md`에 기술 문서 작성

**4. 의사결정 로그 (중요 결정 시)**

`G:/내 드라이브/Obsidian/10. project/Coupong/04-Decisions/결정명.md`에 배경, 결정, 대안 기록

**5. 대화 기록 (중요 대화 종료 시 필수)**

아래 조건에 해당하는 대화가 끝날 때, `G:/내 드라이브/Obsidian/10. project/Coupong/06-Conversations/YYYY-MM-DD-주제.md`에 요약 기록:

기록 대상:
- 새 기능 설계/구현을 논의한 대화
- 복잡한 버그를 해결한 대화
- 아키텍처나 설계 결정을 내린 대화
- 여러 파일을 수정하는 큰 작업을 진행한 대화

기록하지 않는 대화:
- 단순 질문/답변 (1-2턴)
- 파일 내용 확인만 한 대화
- 오타 수정 등 사소한 변경

작성 형식:
```markdown
# Claude와의 대화 - [주제]

#conversation #[태그]

**날짜:** YYYY-MM-DD
**주제:** 대화 주제 한 줄 요약

---

## 대화 개요
2-3줄로 무엇을 논의/작업했는지 요약

## 진행 과정
1. [첫 번째 단계]
2. [두 번째 단계]
...

## 주요 결정/결과
- 결정 사항이나 작업 결과물 목록

## 변경된 파일
- `경로/파일.py` - 변경 내용

## 관련 문서
- [[관련-문서]]
```

주의:
- 같은 날 같은 주제면 기존 파일에 append
- 다른 주제면 새 파일 생성
- `06-Conversations/README.md`의 대화 목록도 업데이트

### 주의사항

- 일일 로그는 **append** (기존 내용 뒤에 추가). 절대 덮어쓰지 마세요
- 시간 형식: `HH:MM` (24시간제)
- 한국어로 작성
- 간결하게 (3-5줄 이내로 요약)
- 코드 블록은 짧게 핵심만

### Python 로거 사용 가능

`obsidian_logger.py`의 `ObsidianLogger` 클래스도 사용 가능:
```python
from obsidian_logger import ObsidianLogger
logger = ObsidianLogger()
logger.log_to_daily("내용", "제목")
logger.log_feature("기능명", "설명")
logger.log_decision("결정명", "배경", "결정")
logger.log_bug("버그명", "설명", "해결방법")
```

### 문서 템플릿

Feature/Technical 문서 작성 시 아래 구조를 따르세요:

```markdown
# 기능명

#feature #태그

**상태:** ✅ 완료 / ⏳ 진행중 / ❌ 미구현
**구현 파일:** `경로/파일.py`

---

## 개요
2-3줄 요약

## 구현 파일
파일 경로 + 핵심 클래스/메서드

## 핵심 로직
코드에서 추출한 실제 동작 방식

## 관련 문서
- [[관련-문서]] - 설명
```
