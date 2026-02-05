# 개발 타임라인

**마지막 업데이트:** 2026-02-05

---

## Phase 1: 데이터 수집 + 마진 분석 + CSV 생성 ✅ (100%)

**기간:** 2026-02-05 완료

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

## ★ Phase 2: 쿠팡 자동 업로드 + 스케줄러 (0%) ← 현재

| 기능 | 상태 | 설명 |
|------|:----:|------|
| Playwright 쿠팡 CSV 업로드 | ❌ | 판매자센터 자동 로그인 + CSV 업로드 |
| 일일 스케줄러 | ❌ | APScheduler / cron 기반 자동 실행 |
| 업로드 결과 확인 | ❌ | 등록 성공/실패 상태 추적 |
| 재고 자동 관리 | ❌ | 품절/재입고 자동 처리 |

---

## Phase 3: 판매 분석 엔진 (0%)

| 기능 | 상태 | 설명 |
|------|:----:|------|
| 쿠팡 판매 데이터 수집 | ❌ | Playwright 크롤링 or API |
| 계정별 성과 분석 | ❌ | 판매액, 권수, 마진 |
| 출판사별 수익성 분석 | ❌ | ROI 계산 |
| Streamlit 대시보드 | ❌ | 판매/마진 시각화 |

---

## Phase 4: 고도화 (0%)

| 기능 | 상태 | 설명 |
|------|:----:|------|
| 경쟁사 가격 모니터링 | ❌ | 자동 가격 조정 |
| 주간/월간 리포트 | ❌ | 자동 생성 |
| 알림 시스템 | ❌ | Telegram/Slack 연동 |
| 신간 자동 감지 | ❌ | 즉시 등록 |

---

## 관련 문서

- [[Dashboard]] - 진행률 + 기능 완료 상태
- [[Index]] - 전체 문서 목차
