# 알라딘 API 사용 가이드

## 🎯 개요

알라딘은 **공식 도서 검색 API**를 무료로 제공합니다.
- 합법적
- 안정적
- 상세한 도서 정보
- 쿠팡 업로드 완벽 대응

---

## 📝 TTBKey 발급 (1분)

### 1단계: 알라딘 접속
```
https://www.aladin.co.kr/ttb/wblog_manage.aspx
```

### 2단계: 로그인
- 알라딘 계정으로 로그인
- 없으면 무료 회원가입

### 3단계: TTB 키 발급
1. "TTB 키 발급" 버튼 클릭
2. 블로그/사이트 정보 입력 (간단히)
3. 키 받기

### 4단계: 키 설정
```bash
# .env 파일 열기
notepad .env

# 아래 줄에 키 입력
ALADIN_TTB_KEY=ttb발급받은키12345
```

---

## 🚀 사용 방법

### 방법 1: 자동 검색 → CSV 생성 (권장)

```bash
python scripts/aladin_to_db.py
```

**흐름:**
1. TTBKey 확인
2. 검색 키워드 입력 (예: "초등수학")
3. 최대 개수 입력 (예: 20개)
4. 자동 검색
5. 결과 미리보기
6. DB 저장 확인
7. CSV 5개 자동 생성
8. 완료!

**소요 시간:** 약 2분

---

### 방법 2: Python 코드에서 직접 사용

```python
from crawlers.aladin_api_crawler import AladinAPICrawler

# 초기화
crawler = AladinAPICrawler(ttb_key="your_ttb_key")

# 키워드 검색
products = crawler.search_by_keyword("초등수학", max_results=20)

for p in products:
    print(f"{p['title']} - {p['original_price']:,}원")

# ISBN 검색
product = crawler.search_by_isbn("9788956746425")
if product:
    print(product['title'])
```

---

## 📊 API 기능

### 1. 키워드 검색 (ItemSearch)

```python
products = crawler.search_by_keyword(
    keyword="초등수학",      # 검색어
    max_results=50,          # 최대 개수
    search_target="Book"     # Book, Music, DVD 등
)
```

**응답 정보:**
- ✅ 제목
- ✅ 저자
- ✅ 출판사
- ✅ 가격
- ✅ ISBN-13
- ✅ 출간일
- ✅ 표지 이미지 URL
- ✅ 설명
- ✅ 페이지 수

### 2. ISBN 검색 (ItemLookUp)

```python
product = crawler.search_by_isbn("9788956746425")
```

**장점:**
- 정확한 매칭
- 상세 정보

---

## 🔄 전체 워크플로우

### 1. 알라딘 검색
```
"초등수학 문제집" 검색
→ 20개 결과
```

### 2. DB 저장
```
kyobo_products 테이블에 저장
(중복 자동 체크)
```

### 3. CSV 생성
```
5개 계정용 CSV 자동 생성
(쿠팡 공식 템플릿)
```

### 4. 쿠팡 업로드
```
판매자센터 > 일괄등록
→ 완료!
```

---

## ⏱️ 시간 비교

| 방법 | 10권 소요시간 | 성공률 |
|------|---------------|--------|
| 수동 입력 | 5분 | 100% |
| 교보 크롤링 | 불가능 | 0% |
| **알라딘 API** | **2분** | **100%** |

---

## 🎁 알라딘 API의 장점

### 1. 합법적
- ✅ 공식 API
- ✅ 약관 위반 없음
- ✅ 안정적 운영

### 2. 상세 정보
- ✅ 저자, 출판사
- ✅ 출간일, 페이지수
- ✅ 고화질 표지 이미지
- ✅ 도서 설명

### 3. 빠름
- ✅ 1초에 50건 검색
- ✅ API 응답 빠름

### 4. 무료
- ✅ 요금 없음
- ✅ 일일 요청 제한 넉넉

---

## 🔒 API 제한

### 요청 제한
- 일일 요청: 5,000건 (충분)
- 초당 요청: 10건

### 주의사항
- TTBKey 노출 금지
- `.env` 파일 Git 제외됨
- 상업적 재판매 금지 (쿠팡 판매는 OK)

---

## 💡 활용 예시

### 예시 1: 특정 시리즈 전부 등록
```python
# "디딤돌 수학" 시리즈 전부 검색
products = crawler.search_by_keyword("디딤돌 수학", max_results=100)

# → DB 저장
# → CSV 생성
# → 쿠팡 업로드
```

### 예시 2: ISBN 리스트 일괄 조회
```python
isbn_list = [
    "9788956746425",
    "9788956746426",
    "9788956746427"
]

for isbn in isbn_list:
    product = crawler.search_by_isbn(isbn)
    # 저장...
```

### 예시 3: 출판사별 검색
```python
# 천재교육 도서 전체
products = crawler.search_by_keyword("천재교육 초등", max_results=100)
```

---

## 🐛 트러블슈팅

### 문제 1: TTBKey 오류
**증상:** "TTBKey가 필요합니다"

**해결:**
1. .env 파일 확인
2. ALADIN_TTB_KEY= 뒤에 키 입력
3. 따옴표 없이 입력

### 문제 2: 검색 결과 없음
**증상:** "검색 결과가 없습니다"

**해결:**
- 키워드 변경 (더 일반적으로)
- 오타 확인
- 영문 → 한글, 한글 → 영문

### 문제 3: API 응답 느림
**증상:** 요청 시간 초과

**해결:**
- 인터넷 연결 확인
- max_results 줄이기
- 잠시 후 재시도

---

## 📚 API 문서

- 공식 문서: http://blog.aladin.co.kr/ttb/category/19154755
- TTB 관리: https://www.aladin.co.kr/ttb/wblog_manage.aspx

---

## 🎉 완성!

이제 다음 명령어로 바로 사용하세요:

```bash
# 1. TTBKey 발급 (1분)
# https://www.aladin.co.kr/ttb/wblog_manage.aspx

# 2. .env에 키 입력

# 3. 실행!
python scripts/aladin_to_db.py
```

**즐거운 쿠팡 판매 되세요! 🚀**
