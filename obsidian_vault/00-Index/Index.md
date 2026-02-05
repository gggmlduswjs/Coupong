# 쿠팡 도서 판매 자동화 시스템

알라딘 API 기반 도서 검색 → 마진 분석 → 묶음 SKU → 쿠팡 CSV 자동 생성

**현재 상태:** Phase 1 완료 | [[Dashboard]]에서 진행률 확인

---

## 문서 목차

### 현황
- [[Dashboard]] - 진행률 + 기능 완료 상태 + 파일 맵
- [[Development-Timeline]] - 개발 타임라인 (Phase 1~4)

### 기능 문서 (02-Features)
- [[Database-Schema-V2]] - 8개 테이블 스키마
- [[알라딘-API-크롤러]] - 알라딘 API 검색 + 도서 수집
- [[연도-추출]] - 제목에서 연도 자동 추출 (87%)
- [[마진-계산기]] - 마진 계산 + 배송정책 결정
- [[묶음-SKU-생성기]] - 저마진 도서 자동 묶음

### 기술 문서 (03-Technical)
- [[시스템-아키텍처]] - 시스템 구조 + 데이터 흐름
- [[Tech-Stack]] - 기술 스택
- [[계정별-통계-쿼리]] - SQL 쿼리 예시

### 의사결정 (04-Decisions)
- [[통계-계산-방식]] - 실시간 계산 vs 캐싱

### 가이드
- [[프로젝트-개요]] - 전체 시스템 상세 개요
- [[사용-가이드]] - 실전 사용법
- [[설정-가이드]] - 초기 설정 및 환경 구성
- [[Claude-Integration]] - Claude-Obsidian 통합

### 일일 로그 (01-Daily)
- [[2026-02-05]] - 최신 개발 로그

---

## 빠른 시작

```bash
# 전체 파이프라인
python scripts/run_pipeline.py --max-results 50

# 특정 출판사만
python scripts/run_pipeline.py --publishers 개념원리 길벗
```

---

#project #automation #coupang #books
