# 알라딘 API 크롤러

#feature #crawler #api

**상태:** ✅ 완료
**구현 파일:** `crawlers/aladin_api_crawler.py`

---

## 개요

알라딘 Open API를 통해 24개 거래 출판사의 도서를 검색하고, ISBN/제목/가격 등 메타데이터를 수집하여 DB에 저장한다.
**최신순 정렬 + 2025년 이후 필터**로 최근 도서만 수집.

## API 정보

- **Base URL:** `http://www.aladin.co.kr/ttb/api/`
- **인증:** TTBKey (`.env`의 `ALADIN_TTB_KEY`)
- **엔드포인트:** `ItemSearch.aspx` (키워드 검색), `ItemLookUp.aspx` (ISBN 조회)
- **정렬:** `Sort=PublishTime` (최신 출간순)
- **연도 필터:** `year_filter=2025` → 2025년 이전 도서 도달 시 조기 종료

## 출판사 별칭 시스템

알라딘과 우리 DB의 출판사명이 다른 경우 자동 매칭:

```python
PUBLISHER_ALIASES = {
    "씨톡":           ["씨앤톡", "C&Talk"],
    "능률교육":       ["NE능률", "NE능률(참고서)", "NE Build&Grow"],
    "크라운":         ["크라운출판사", "크라운Publishing"],
    "동아":           ["동아출판", "동아출판(사전)"],
    "영진":           ["영진닷컴", "영진.com(영진닷컴)", "영진문화사"],
    "이퓨쳐":         ["e-future", "이퓨처"],
    "지학사":         ["지학사(참고서)"],
    "이투스":         ["이투스북"],
    "EBS":            ["한국교육방송공사", "EBS한국교육방송공사"],
    "한국교육방송공사": ["EBS"],
}
```

### 별칭 동작 방식

1. **검색 단계**: `get_search_names()` — 원래 이름 + 별칭 모두로 알라딘 검색
   - 예: "씨톡" 검색 → "씨톡", "씨앤톡", "C&Talk" 3번 검색
2. **매칭 단계**: `_match_publisher_name()` — API 반환 출판사명이 별칭에 포함되면 매칭
   - 예: API가 "씨앤톡" 반환 → DB "씨톡"과 매칭 성공

## 핵심 메서드

### `search_by_keyword(keyword, max_results, sort, year_filter)`

```python
search_by_keyword(
    keyword="동아출판",
    max_results=200,
    sort="PublishTime",    # 최신순 (기본값)
    year_filter=2025,      # 2025년 이후만
)
```

- **sort 옵션**: `PublishTime`(최신순), `Accuracy`(관련도), `SalesPoint`(판매량)
- **year_filter**: `publish_date`가 기준 연도 이전이면 스킵, 최신순 정렬 시 조기 종료
- 반환: `[{isbn, title, author, publisher, original_price, publish_date, year, ...}]`

### `search_by_isbn(isbn)`
- 단일 ISBN으로 도서 조회

### `_parse_item(item)`
- API 응답 → 내부 포맷 변환
- `Book.extract_year()`, `normalize_title()`, `extract_series()` 자동 호출
- 이미지 URL: `coversum` → `cover500` 자동 변환 (쿠팡 500x500 권장)

### `get_search_names(publisher_name)` → `List[str]`
- 원래 이름 + `PUBLISHER_ALIASES` 별칭 목록 반환

### `_match_publisher_name(api_publisher, target_name)` → `bool`
- 부분 일치 + 별칭 매칭

## 크롤링 흐름

```
출판사 24개 순회
  ├─ get_search_names("씨톡") → ["씨톡", "씨앤톡", "C&Talk"]
  ├─ 각 이름으로 search_by_keyword(sort=PublishTime, year_filter=2025)
  │   ├─ 알라딘 API 호출 (페이지네이션)
  │   ├─ publish_date < 2025 도달 → 조기 종료
  │   └─ 출판사명 매칭 필터
  ├─ ISBN 중복 체크 (배치 내 + DB)
  └─ Book 테이블 INSERT
```

## 수집 통계 (2026-02-05 최종)

| 항목 | 수치 |
|------|------|
| 활성 출판사 | 24개 |
| 총 도서 | 1,189권 |
| 출간 연도 | 2025~2026년만 |
| 등록 가능 상품 | 1,189개 |
| 출판사당 최대 검색 | 200건 |

### 출판사별 도서 수

| 출판사      | 도서 수  | 별칭 필요    |
| -------- | ----- | -------- |
| 영진       | 113   | 영진닷컴     |
| 동아       | 109   | 동아출판     |
| 지학사      | 75    | 지학사(참고서) |
| 씨톡       | 68    | 씨앤톡      |
| 이투스      | 60    | 이투스북     |
| 한국교육방송공사 | 56    | EBS      |
| 이퓨쳐      | 55    | e-future |
| 능률교육     | 54    | NE능률     |
| 한빛미디어    | 52    | -        |
| 길벗       | 52    | -        |
| 이지스퍼블리싱  | 52    | -        |
| 렉스미디어    | 52    | -        |
| 기타 12개   | 50~51 | -        |

## 대시보드 연동

`dashboard.py`의 "신규 등록" 메뉴에서 크롤링 버튼 제공:
- `FranchiseSync.crawl_by_publisher()` 호출
- 출판사당 최대 수집 수, 연도 필터 설정 가능
- 진행률 바 표시

## 관련 문서

- [[프랜차이즈-동기화]] - 크롤링 → 분석 → 등록 전체 파이프라인
- [[연도-추출]] - 크롤링 시 연도 자동 추출
- [[Database-Schema-V2]] - books 테이블 구조
- [[마진-계산기]] - 수집된 정가로 마진 분석
