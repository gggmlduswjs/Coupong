# 빠른 참조 가이드

## 🚀 3단계 시작

### 1단계: 초기 설정 (1회, 5분)

```bash
# 알라딘 TTBKey 발급
https://www.aladin.co.kr/ttb/wblog_manage.aspx

# .env 파일 설정
ALADIN_TTB_KEY=발급받은키

# DB 초기화
python scripts/init_db_v2_clean.py
```

### 2단계: 스마트 업로드

```bash
python scripts/smart_upload_system.py
```

### 3단계: 쿠팡 업로드

```
data/uploads/ 폴더 → 쿠팡 판매자센터 일괄등록
```

---

## 📋 주요 명령어

| 명령어 | 용도 |
|--------|------|
| `python scripts/init_db_v2_clean.py` | DB 초기화 + 출판사 등록 |
| `python scripts/smart_upload_system.py` | 전체 자동 워크플로우 |
| `python scripts/test_year_extraction.py` | 연도 추출 테스트 |
| `python scripts/test_aladin_year.py` | 알라딘 API 테스트 |
| `python analyzers/margin_calculator.py` | 마진 계산기 테스트 |
| `python analyzers/bundle_generator.py` | 묶음 생성기 테스트 |

---

## 🎯 핵심 규칙

### 도서정가제
```python
sale_price = list_price * 0.9  # 정가의 90% 고정
```

### 중복 방지
```python
UNIQUE(account_id, isbn)  # 계정별 ISBN 중복 금지
```

### 배송 정책
```python
순마진 >= 2000원 → 무료배송
순마진 >= 0원    → 유료배송
순마진 < 0원     → 묶음 필수
```

### 묶음 조건
```
- 동일 출판사
- 동일 시리즈
- 동일 연도
- 2~5권
```

---

## 📊 출판사 매입률

| 매입률 | 출판사 | 무료배송 기준 |
|--------|--------|--------------|
| 40% | 마린북스 등 4개 | 9,000원 |
| 55% | 크라운, 영진 | 14,400원 |
| 60% | 길벗 등 5개 | 18,000원 |
| 65% | 개념원리 등 10개 | 23,900원 |
| 67% | 동아 | 27,600원 |
| 70% | 좋은책신사고 | 35,800원 |
| 73% | EBS | 50,800원 |

---

## 🔧 트러블슈팅

### TTBKey 오류
```bash
# .env 파일 확인
ALADIN_TTB_KEY=your_key
```

### DB 초기화 필요
```bash
python scripts/init_db_v2_clean.py
```

### 연도 추출 확인
```bash
python scripts/test_year_extraction.py
```

---

## 📚 문서

- **IMPLEMENTATION_COMPLETE.md** - 전체 구현 상황
- **DATABASE_SCHEMA_V2.md** - DB 스키마
- **ALADIN_API_GUIDE.md** - API 사용법
- **AUTO_UPDATE_GUIDE.md** - 자동화 가이드
- **이 문서** - 빠른 참조

---

## 🎁 자동 vs 수동

| 작업 | 수동 | 자동 |
|------|------|------|
| 도서 검색 | 1시간/일 | 자동 |
| 마진 계산 | 5분/권 | 자동 |
| 중복 체크 | 2분/권 | 자동 |
| CSV 생성 | 30분 | 1분 |

**절감: 월 56시간**

---

## 💰 예상 수익

```
일일 신규: 40개
월 전환: 60권 (5%)
권당 마진: 8,000원
───────────────
월 수익: 480,000원
연 수익: 5,760,000원
```

---

## ⚡ 핵심 포인트

1. **출판사 24개만** - 리스트 엄격 준수
2. **도서정가제** - 정가의 90% 고정
3. **중복 방지** - (계정, ISBN) 유니크
4. **연도 추출** - 판본 구분 필수
5. **마진 기반** - 자동 배송정책 결정

---

**바로 시작: `python scripts/smart_upload_system.py`**
