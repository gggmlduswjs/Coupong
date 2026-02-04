# 🚀 바로 시작하기

## ✅ 완료된 것
- [x] 프로젝트 구조 생성
- [x] DB 모델 설계 (7개 테이블)
- [x] 교보문고 크롤러
- [x] CSV 업로더
- [x] Playwright 자동 업로더
- [x] 계정 정보 암호화
- [x] **5개 계정 등록 완료**

---

## 🎯 지금 바로 실행 (5분)

### 1단계: 가상환경 설정 (2분)

```bash
# 프로젝트 폴더로 이동
cd C:\Users\MSI\Desktop\Coupong

# 가상환경 생성
python -m venv venv

# 가상환경 활성화
venv\Scripts\activate

# 패키지 설치
pip install -r requirements.txt

# Playwright 브라우저 설치
playwright install chromium
```

### 2단계: 데이터베이스 + 계정 등록 (1분)

```bash
# DB 테이블 생성
python scripts/init_db.py

# 5개 계정 암호화 저장
python scripts/register_accounts.py
```

**예상 출력:**
```
✅ 신규 등록: account_1 (007-book)
✅ 신규 등록: account_2 (007-ez)
✅ 신규 등록: account_3 (007-bm)
✅ 신규 등록: account_4 (002-bm)
✅ 신규 등록: account_5 (big6ceo)
```

### 3단계: 전체 시스템 테스트 (2분)

```bash
python scripts/quick_start.py
```

**자동으로 실행됨:**
1. 교보문고에서 "초등교재" 5개 크롤링
2. SQLite DB에 저장
3. 쿠팡용 CSV 5개 생성 (계정별)

**결과 확인:**
```bash
dir data\uploads
```

---

## 📦 생성된 파일

```
Coupong/
├── .env                        # ✅ 계정 정보 (암호화 키 포함)
├── coupang_auto.db             # ✅ SQLite DB (생성됨)
├── data/uploads/               # ✅ CSV 파일들
│   ├── coupang_upload_account_1_*.csv
│   ├── coupang_upload_account_2_*.csv
│   ├── coupang_upload_account_3_*.csv
│   ├── coupang_upload_account_4_*.csv
│   └── coupang_upload_account_5_*.csv
└── sessions/                   # 로그인 세션 (나중에)
```

---

## 🎉 다음 할 일

### 옵션 1: CSV 수동 업로드 (지금 바로)
1. `data/uploads/` 폴더 열기
2. 5개 CSV 파일 확인
3. 쿠팡 판매자센터 → 상품관리 → 대량등록
4. 각 계정에 맞는 CSV 업로드

### 옵션 2: 자동 업로드 테스트 (선택)
```bash
python scripts/test_login.py
```
- 5개 계정 자동 로그인 테스트
- 세션 저장

### 옵션 3: API 서버 실행
```bash
uvicorn app.main:app --reload
# http://localhost:8000/docs
```

---

## 📊 등록된 계정

| 계정 | ID | 상태 |
|------|-----|------|
| account_1 | 007-book | 🟢 활성 |
| account_2 | 007-ez | 🟢 활성 |
| account_3 | 007-bm | 🟢 활성 |
| account_4 | 002-bm | 🟢 활성 |
| account_5 | big6ceo | 🟢 활성 |

**비밀번호:** DB에 암호화되어 안전하게 저장됨

---

## 🔐 보안 주의사항

### ⚠️ 절대 하면 안 되는 것
- ❌ `.env` 파일을 Git에 커밋
- ❌ 계정 정보를 카톡/이메일로 전송
- ❌ 암호화 키를 공유
- ❌ 세션 파일을 업로드

### ✅ 이미 안전하게 처리된 것
- ✅ `.gitignore`에 `.env` 포함
- ✅ 비밀번호 Fernet 암호화
- ✅ 세션 파일 Git 제외

---

## 📝 일상 사용 방법

### 매일 아침 (10분)

```bash
# 1. 가상환경 활성화
cd C:\Users\MSI\Desktop\Coupong
venv\Scripts\activate

# 2. 신간 크롤링 + CSV 생성
python scripts/quick_start.py

# 3. CSV 확인
explorer data\uploads

# 4. 쿠팡에 수동 업로드
```

---

## 🚀 앞으로 구현할 것

### Phase 1: 완전 자동화 (1~2주)
- [ ] Playwright 자동 업로드 완성
- [ ] 5개 계정 순회 업로드
- [ ] 판매 데이터 수집

### Phase 2: 분석 (2~3주)
- [ ] 노출 vs 전환 분류
- [ ] 우선순위 액션 추천
- [ ] Streamlit 대시보드

### Phase 3: 고도화 (1개월~)
- [ ] Celery 스케줄러
- [ ] LLM 상품명 최적화
- [ ] A/B 테스트

---

## 📞 문제 발생 시

### 자주 묻는 질문

**Q: ModuleNotFoundError가 나요**
```bash
venv\Scripts\activate  # 가상환경 활성화 확인
pip install -r requirements.txt
```

**Q: Playwright 오류**
```bash
playwright install chromium --force
```

**Q: DB 오류**
```bash
del coupang_auto.db
python scripts/init_db.py
python scripts/register_accounts.py
```

---

## 📖 더 보기

- `ARCHITECTURE.md` - 전체 시스템 설계
- `README.md` - 프로젝트 설명
- `QUICKSTART.md` - 빠른 시작 가이드
- `PROJECT_SUMMARY.md` - 완성 현황

---

**🎉 설치 완료! 이제 쿠팡 도서 판매를 자동화하세요!**
