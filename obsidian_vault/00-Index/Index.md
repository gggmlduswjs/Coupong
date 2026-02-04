# 쿠팡 도서 판매 자동화 시스템

**마지막 업데이트:** 2026-02-05
**상태:** 프로덕션 준비 완료 ✅

---

## 🎯 프로젝트 개요

알라딘 API 기반 도서 검색 → 마진 분석 → 묶음 SKU 생성 → 쿠팡 자동 업로드

**핵심 기능:**
- 24개 출판사 (40%-73% 마진율)
- 도서정가제 100% 준수 (정가 × 0.9)
- 연도 자동 추출 (87% 성공률)
- 자동 마진 계산 및 배송 정책 결정
- 저마진 도서 자동 묶음
- (계정, ISBN) 중복 방지
- 5개 계정 자동 분산 업로드

상세 정보: [[프로젝트-개요]]

---

## 📖 문서 목차

### 🏠 시작하기
- [[프로젝트-개요]] - 전체 시스템 개요 및 워크플로우
- [[사용-가이드]] - 빠른 시작 및 사용법
- [[설정-가이드]] - 초기 설정 및 환경 구성
- [[Claude-Integration]] - Claude-Obsidian 통합 가이드

### 📊 개발 현황
- [[Development-Timeline]] - 개발 타임라인
- [[2026-02-05]] - 오늘의 개발 로그

### 🎨 기능 문서
- [[Database-Schema-V2]] - 데이터베이스 스키마 (8개 테이블)
- [[마진-계산기]] - 마진 계산 및 배송 정책
- [[연도-추출]] - 도서 제목에서 연도 자동 추출
- [[묶음-SKU-생성기]] - 저마진 도서 자동 묶음

### 🔧 기술 문서
- [[시스템-아키텍처]] - 시스템 구조 및 데이터 흐름
- [[Tech-Stack]] - 기술 스택 상세
- [[계정별-통계-쿼리]] - SQL 쿼리 예시

### 🤔 의사결정 기록
- [[통계-계산-방식]] - 실시간 계산 vs 캐싱

---

## 📊 개발 현황

### 완료된 기능 ✅

**Core System**
- [x] Database V2 스키마 (8개 테이블)
- [x] 24개 출판사 설정 (마진율, 공급률, 무료배송 기준)
- [x] SQLAlchemy 모델 구현
- [x] UNIQUE 제약조건 (중복 방지)

**Data Collection**
- [x] 알라딘 API 크롤러
- [x] 연도 자동 추출 (87% 성공률)
- [x] 시리즈 정규화

**Analysis**
- [x] 자동 마진 계산
- [x] 배송 정책 자동 결정
- [x] 수익성 평가

**Bundling**
- [x] 묶음 SKU 자동 생성
- [x] 시리즈별 그룹화
- [x] 순마진 기준 필터링

**Distribution**
- [x] 5개 계정 분산 업로드
- [x] DB 레벨 중복 체크
- [x] CSV 생성 (쿠팡 포맷)

**Documentation**
- [x] Obsidian 실시간 로깅
- [x] 일일 개발 로그 자동 생성
- [x] 기능/기술/결정 문서화
- [x] Claude-Obsidian 통합 가이드

### 대기 중 ⏳

**Phase 2: 분석 엔진**
- [ ] 판매 데이터 수집
- [ ] 계정별 성과 분석
- [ ] 출판사별 수익성 분석
- [ ] Streamlit 대시보드

**Phase 3: 자동화 확장**
- [ ] 쿠팡 자동 업로드 (Selenium)
- [ ] 재고 자동 관리
- [ ] 일일 자동 크롤링 스케줄러
- [ ] 가격 자동 조정

---

## 🚀 빠른 시작

### 1. DB 초기화
```bash
python scripts/init_db_v2_clean.py
```

### 2. 전체 워크플로우 실행
```bash
python scripts/smart_upload_system.py
```

### 3. CSV 확인
```
output/coupang_upload_account_1.csv
output/coupang_upload_account_2.csv
...
```

상세 가이드: [[사용-가이드]]

---

## 📁 프로젝트 구조

```
C:\Users\MSI\Desktop\Coupong\
│
├── app/
│   ├── models/          (데이터 모델)
│   │   ├── publisher.py
│   │   ├── book.py
│   │   ├── product.py
│   │   ├── bundle_sku.py
│   │   └── listing.py
│   ├── config.py        (설정)
│   └── database.py      (DB 연결)
│
├── crawlers/
│   └── aladin_api_crawler.py
│
├── analyzers/
│   ├── margin_calculator.py
│   └── bundle_generator.py
│
├── exporters/
│   └── csv_generator.py
│
├── scripts/
│   ├── init_db_v2_clean.py
│   └── smart_upload_system.py
│
├── obsidian_vault/      (문서)
│   ├── 00-Index/
│   ├── 01-Daily/
│   ├── 02-Features/
│   ├── 03-Technical/
│   └── 04-Decisions/
│
├── obsidian_logger.py   (자동 로깅)
├── coupang.db           (SQLite DB)
└── .env                 (환경 변수)
```

---

## 💡 핵심 개념

### 마진 계산
```
순마진 = (판매가 - 공급원가 - 쿠팡수수료) - 배송비
      = (정가×0.9 - 정가×공급률 - 판매가×0.11) - 2000
```

### 배송 정책
- **순마진 >= 2000원** → 무료배송 (단권 업로드)
- **순마진 >= 0원** → 유료배송 (단권 업로드)
- **순마진 < 0원** → 묶음 필요 (자동 묶음 생성)

### 중복 방지
```sql
UNIQUE(account_id, isbn)         -- 단권 중복 방지
UNIQUE(account_id, bundle_key)   -- 묶음 중복 방지
```

---

## 📊 통계

### 데이터베이스
- **8개 테이블** (publishers, books, products, bundle_skus, listings, accounts, sales, analysis_results)
- **24개 출판사** (40%-73% 마진율)
- **5개 계정** (일일 20개 업로드 한도)

### 성능
- **연도 추출:** 87% 성공률
- **중복 체크:** DB 레벨 (100% 정확)
- **묶음 생성:** 자동 (시리즈별 그룹화)

---

## 🔗 외부 링크

### APIs
- [알라딘 Open API](https://www.aladin.co.kr/ttb/wstart.aspx)
- [알라딘 API 문서](https://blog.aladin.co.kr/openapi/category/9854908)

### 도구
- [Obsidian 다운로드](https://obsidian.md/download)
- [Claude API Console](https://console.anthropic.com/)

---

## 📝 최근 업데이트

### 2026-02-05
- ✅ 프로젝트 개요 문서 작성
- ✅ 시스템 아키텍처 문서 작성
- ✅ 사용 가이드 작성
- ✅ 설정 가이드 작성
- ✅ 묶음 SKU 생성기 상세 문서
- ✅ Claude-Obsidian 통합 가이드

---

## 🏷️ 태그

#project #automation #coupang #books #aladin #margin #bundle #obsidian

---

**프로젝트 상태: 프로덕션 준비 완료 ✅**

**다음 단계: 알라딘 TTBKey 발급 후 실제 운영**
