# Dashboard

**마지막 업데이트:** 2026-02-05

---

## 전체 진행률

| Phase | 내용 | 상태 | 완료율 |
|-------|------|------|--------|
| **Phase 1** | 데이터 수집 + 마진 분석 + CSV 생성 | ✅ 완료 | 100% |
| **Phase 2** | 쿠팡 자동 업로드 + 스케줄러 | ⏳ 대기 | 0% |
| **Phase 3** | 판매 분석 엔진 + 대시보드 | ⏳ 대기 | 0% |
| **Phase 4** | 가격 모니터링 + 알림 + 고도화 | ⏳ 대기 | 0% |

**현재 위치: Phase 1 완료, Phase 2 준비 중**

---

## 기능별 완료 상태

| 기능 | 코드 | 문서 | 비고 |
|------|:----:|:----:|------|
| DB 스키마 (8 테이블) | ✅ | ✅ | `app/models/` |
| 알라딘 API 크롤러 | ✅ | ✅ | 981개 도서 수집 |
| 연도 추출 | ✅ | ✅ | 87% 성공률 |
| 마진 계산기 | ✅ | ✅ | 배송정책 자동 결정 |
| 묶음 SKU 생성기 | ✅ | ✅ | 시리즈+연도 그룹화 |
| 쿠팡 CSV 생성 (V4.5) | ✅ | ✅ | 113컬럼 |
| 5계정 분산 업로드 | ✅ | ✅ | 중복 방지 |
| 파이프라인 자동화 | ✅ | ✅ | `run_pipeline.py` |
| 기존 상품 import | ✅ | ✅ | `import_existing_products.py` |
| Obsidian 자동 로깅 | ✅ | ✅ | `obsidian_logger.py` |
| 쿠팡 자동 업로드 | ❌ | ❌ | Phase 2 |
| 일일 스케줄러 | ❌ | ❌ | Phase 2 |
| 판매 데이터 수집 | ❌ | ❌ | Phase 3 |
| Streamlit 대시보드 | ❌ | ❌ | Phase 3 |
| 가격 모니터링 | ❌ | ❌ | Phase 4 |
| 알림 시스템 | ❌ | ❌ | Phase 4 |

---

## 구현 파일 맵

| 기능 | 파일 | 핵심 클래스/메서드 |
|------|------|-------------------|
| DB 모델 | `app/models/*.py` | Book, Publisher, Product, BundleSKU, Listing |
| 출판사 설정 | `config/publishers.py` | 24개 출판사 매입율/공급률 |
| 알라딘 크롤링 | `crawlers/aladin_api_crawler.py` | `AladinAPICrawler.search_by_keyword()` |
| 마진 분석 | `analyzers/margin_calculator.py` | `MarginCalculator.analyze_book()` |
| 묶음 생성 | `analyzers/bundle_generator.py` | `BundleGenerator.auto_generate_bundles()` |
| CSV 생성 | `uploaders/coupang_csv_generator.py` | `CoupangCSVGenerator.generate_csv()` |
| 파이프라인 | `scripts/run_pipeline.py` | 5단계 자동화 |
| 상품 import | `scripts/import_existing_products.py` | 기존 쿠팡 상품 DB 등록 |
| Obsidian 로깅 | `obsidian_logger.py` | `ObsidianLogger` |
| 자동 로깅 | `auto_logger.py` | `@task_context` 데코레이터 |

---

## 데이터 현황

| 항목 | 수량 |
|------|------|
| 출판사 | 24개 (매입율 40%~73%) |
| 수집 도서 | 981개 |
| 단권 상품 | 981개 |
| 쿠팡 계정 | 5개 |
| 등록 현황 | 4,765개 |

---

## 다음 할 일 (우선순위)

1. **Playwright 쿠팡 자동 업로드** - CSV를 판매자센터에 자동 등록
2. **일일 스케줄러** - 매일 신간 검색 + CSV 생성 자동화
3. **업로드 결과 추적** - 등록 성공/실패 상태 확인
4. **판매 데이터 수집** - 쿠팡 판매 현황 크롤링

---

## 관련 문서

- [[Index]] - 전체 문서 목차
- [[Development-Timeline]] - 개발 타임라인
