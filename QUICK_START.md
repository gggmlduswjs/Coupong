# 빠른 시작 가이드

## 🚀 5분 안에 시작하기

### 1단계: 알라딘 키 발급 (1분)

```
https://www.aladin.co.kr/ttb/wblog_manage.aspx
→ 로그인 → TTB 키 발급
```

### 2단계: 키 입력 (30초)

`.env` 파일 열기:
```
ALADIN_TTB_KEY=여기에_발급받은_키_입력
```

### 3단계: 실행 (3분)

```bash
# 대화형 모드 (처음 사용 시)
python scripts/auto_search_publishers.py

# 또는 완전 자동 모드
python scripts/scheduled_auto_update.py
```

### 4단계: 쿠팡 업로드

```
쿠팡 판매자센터
→ 상품관리
→ 일괄등록
→ data/uploads/ 폴더의 CSV 파일 업로드
```

---

## 📁 주요 파일

| 파일 | 용도 |
|------|------|
| `scripts/auto_search_publishers.py` | 대화형 검색 (출판사 선택 가능) |
| `scripts/scheduled_auto_update.py` | 완전 자동 검색 (스케줄링용) |
| `config/publishers.py` | 출판사 설정 (24개) |
| `AUTO_UPDATE_GUIDE.md` | 상세 가이드 |

---

## 🎯 취급 출판사 (24개)

- **매입률 40%:** 마린북스, 아카데미소프트, 렉스미디어, 해람북스
- **매입률 55%:** 크라운, 영진
- **매입률 60%:** 이퓨쳐, 사회평론, 길벗, 아티오, 이지스퍼블리싱
- **매입률 65%:** 개념원리, 이투스, 비상교육, 능률교육, 씨톡, 지학사, 수경출판사, 쏠티북스, 마더텅, 한빛미디어
- **매입률 67%:** 동아
- **매입률 70%:** 좋은책신사고
- **매입률 73%:** EBS

---

## ⚙️ 설정 변경

### 검색 조건 변경

`scripts/scheduled_auto_update.py` 파일:

```python
CONFIG = {
    "max_per_publisher": 20,     # 출판사당 검색 개수
    "recent_days": 180,           # 최근 N일 이내
    "min_price": 5000,            # 최소 가격
    "max_price": 100000,          # 최대 가격
}
```

### 출판사 추가

`config/publishers.py` 파일:

```python
{"name": "새출판사", "margin": 60, "min_free_shipping": 18000},
```

---

## 🤖 자동화 설정

### Windows 작업 스케줄러

```
1. Win + R → taskschd.msc
2. 새 작업 만들기
3. 프로그램: C:\Users\MSI\Desktop\Coupong\scripts\run_auto_update.bat
4. 트리거: 매일 오전 9시
5. 저장
```

**결과:** 매일 자동으로 최신 도서 검색 및 CSV 생성!

---

## 📊 예상 수익

### 예시: 개념원리 수학 (15,000원)

```
판매가:    13,500원 (정가의 90%)
매입가:     5,250원 (매입률 65%)
쿠팡수수료: 1,350원 (10%)
─────────────────────
순수익:     6,900원 (51% 마진)
```

---

## 📝 로그 확인

```
logs/auto_update_20260205.log
```

---

## 🐛 문제 해결

### 검색 결과가 없어요
→ `.env`에서 `ALADIN_TTB_KEY` 확인

### CSV가 생성 안돼요
→ 새 도서가 없거나 모두 중복 (정상)

### 작업 스케줄러가 안돼요
→ 배치 파일 경로 확인

---

## 📚 더 알아보기

- **상세 가이드:** `AUTO_UPDATE_GUIDE.md`
- **알라딘 API:** `ALADIN_API_GUIDE.md`
- **시스템 구조:** `ARCHITECTURE.md`

---

## 🎉 완료!

```bash
# 지금 바로 시작
python scripts/auto_search_publishers.py
```

**행복한 판매 되세요! 🚀**
