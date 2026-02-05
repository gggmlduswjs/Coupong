# 알라딘 API 크롤러

#feature #crawler #api

**상태:** ✅ 완료
**구현 파일:** `crawlers/aladin_api_crawler.py`

---

## 개요

알라딘 Open API를 통해 24개 출판사의 도서를 검색하고, ISBN/제목/가격 등 메타데이터를 수집하여 DB에 저장한다.

## API 정보

- **Base URL:** `http://www.aladin.co.kr/ttb/api/`
- **인증:** TTBKey (`.env`에 저장)
- **검색 방식:** 출판사명을 키워드로 검색
- **제한:** 출판사당 최대 50건

## 핵심 메서드

### `search_by_keyword(keyword, max_results, search_target)`
- 키워드(출판사명)로 도서 검색
- `search_target`: "Book" (기본값)
- 반환: `[{isbn, title, author, publisher, original_price, ...}]`

### `search_by_isbn(isbn)`
- 단일 ISBN으로 도서 조회

### `_parse_item(item)`
- API 응답을 파싱하여 내부 포맷으로 변환
- `Book.extract_year()`, `normalize_title()`, `extract_series()` 자동 호출
- 반환 필드: isbn, title, author, publisher, original_price, year, normalized_title, normalized_series, image_url, description, publish_date, page_count

## 파이프라인 내 위치

```
[Stage 2] 알라딘 API 검색
    ↓
24개 출판사 × 최대 50건 = 최대 1,200건 검색
    ↓
ISBN 중복 체크 후 DB 저장
    ↓
981개 도서 수집 완료 (2026-02-05 기준)
```

## 사용법

```bash
# 전체 출판사 검색
python scripts/run_pipeline.py --max-results 50

# 특정 출판사만
python scripts/run_pipeline.py --publishers 개념원리 길벗

# 미리보기 (저장 안 함)
python scripts/run_pipeline.py --dry-run
```

## 수집 통계 (2026-02-05)

| 항목 | 수치 |
|------|------|
| 검색 대상 출판사 | 24개 |
| API 호출 횟수 | 24회 |
| 수집 도서 | 981개 |
| 소요 시간 | ~33초 |
| 중복 건수 | ISBN UNIQUE로 자동 필터링 |

## 관련 문서

- [[연도-추출]] - 크롤링 시 연도 자동 추출
- [[Database-Schema-V2]] - books 테이블에 저장
- [[마진-계산기]] - 수집된 정가로 마진 분석
