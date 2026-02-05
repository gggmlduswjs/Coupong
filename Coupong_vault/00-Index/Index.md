# 쿠팡 도서 판매 자동화 시스템

알라딘 API → 마진 분석 → 묶음 SKU → 쿠팡 WING API 자동 등록

**현재 상태:** Phase 2 (95%) + Phase 3 (80%) 동시 진행중 | [[Dashboard]]에서 진행률 확인
- 대시보드 v3.2 운영중 (Tailscale HTTPS)
- 매출 동기화 962건, 자동 크롤링 매일 03:00
- 출판사 55개, 도서 2,535개, Listings 15,363개

---

## 문서 목차

### 현황
- [[Dashboard]] - 진행률 + 기능 완료 상태 + 5계정 현황 + 파일 맵
- [[Development-Timeline]] - 개발 타임라인 (Phase 1~4)

### 기능 문서 (02-Features)
- [[Database-Schema-V2]] - 9개 테이블 스키마 (RevenueHistory 추가)
- [[알라딘-API-크롤러]] - 알라딘 API 검색 + 도서 수집 (2,535개)
- [[연도-추출]] - 제목에서 연도 자동 추출 (87%)
- [[마진-계산기]] - 마진 계산 + 배송정책 결정
- [[묶음-SKU-생성기]] - 저마진 도서 자동 묶음
- [[쿠팡-API-연동]] - WING API 클라이언트 + 상품 동기화 + API 등록 (핵심)
- [[쿠팡-엑셀-동기화]] - ~~엑셀 기반 동기화~~ → WING API로 대체됨
- [[매출-분석-대시보드]] - Streamlit v3.2 대시보드 + KPI + 매출 인사이트
- [[자동-크롤링-스케줄러]] - 매일 03:00 자동 크롤링 데몬
- [[프랜차이즈-동기화]] - 55개 출판사 프랜차이즈 동기화

### 기술 문서 (03-Technical)
- [[시스템-아키텍처]] - 시스템 구조 + 데이터 흐름 (CSV + API 이중 경로)
- [[Tech-Stack]] - 기술 스택 (WING API HMAC 인증 포함)
- [[파일-구조]] - 전체 디렉토리 + 파일별 역할
- [[계정별-통계-쿼리]] - SQL 쿼리 예시
- [[글로벌-Obsidian-자동로깅]] - 글로벌 훅 시스템으로 자동 개발 기록
- [[대시보드-접속-가이드]] - Tailscale HTTPS 배포 + 접속 방법

### 의사결정 (04-Decisions)
- [[통계-계산-방식]] - 실시간 계산 vs 캐싱
- [[코드-정리-계획]] - Phase 1.5 정리

### 가이드
- [[사용-가이드]] - 파이프라인 + API 등록 실전 사용법
- [[설정-가이드]] - 초기 설정 + WING API 키 + 환경 구성
- [[Claude-Integration]] - Claude Code + Obsidian 개발 워크플로우

### 일일 로그 (01-Daily)
- [[2026-02-05]] - 최신 개발 로그

---

## 빠른 시작

```bash
# 전체 파이프라인 (알라딘 검색 → 마진 분석 → 동기화 → CSV)
python scripts/run_pipeline.py --max-results 50

# 특정 출판사만
python scripts/run_pipeline.py --publishers 개념원리 길벗

# WING API 상품 동기화 (5계정 기존 상품 DB 반영)
python scripts/sync_coupang_products.py

# API 상품 등록 테스트
python scripts/test_api_upload.py --account 007-book --isbn 9788961334839

# 대시보드 실행
streamlit run dashboard.py --server.port 8503

# 매출 동기화 (최근 30일)
python scripts/sync_revenue.py

# 자동 크롤링 즉시 실행
python scripts/auto_crawl.py --now

# 자동 크롤링 데몬 (매일 03:00)
python scripts/auto_crawl.py
```

---

#project #automation #coupang #books #wing-api
