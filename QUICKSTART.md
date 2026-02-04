# 🚀 빠른 시작 가이드

## 10분 안에 시작하기

### 1단계: 환경 설정 (3분)

```bash
# 1. 가상환경 생성
python -m venv venv

# 2. 가상환경 활성화
# Windows:
venv\Scripts\activate

# Mac/Linux:
source venv/bin/activate

# 3. 패키지 설치
pip install -r requirements.txt

# 4. Playwright 브라우저 설치
playwright install chromium
```

### 2단계: 환경변수 설정 (2분)

```bash
# .env 파일 생성
cp .env.example .env
```

`.env` 파일 열어서 최소한 이것만 수정:

```env
# 암호화 키 생성
ENCRYPTION_KEY=<아래 명령으로 생성>
```

암호화 키 생성:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3단계: 데이터베이스 초기화 (1분)

```bash
python scripts/init_db.py
```

### 4단계: MVP 테스트 (5분)

```bash
python scripts/quick_start.py
```

이 스크립트가 자동으로:
1. 교보문고에서 5개 상품 크롤링
2. DB에 저장
3. 5개 계정용 CSV 파일 생성

---

## 결과 확인

### 생성된 파일

```
data/uploads/
├── coupang_upload_account_1_20250204_120000.csv
├── coupang_upload_account_2_20250204_120001.csv
├── coupang_upload_account_3_20250204_120002.csv
├── coupang_upload_account_4_20250204_120003.csv
└── coupang_upload_account_5_20250204_120004.csv
```

### 쿠팡 업로드

1. 쿠팡 판매자센터 로그인
2. 상품관리 → 대량등록
3. 생성된 CSV 파일 업로드

---

## 다음 단계

### 옵션 1: 수동 운영 (바로 사용 가능)
```bash
# 매일 크롤링
python scripts/quick_start.py

# CSV 파일 수동 업로드
```

### 옵션 2: API 서버 실행
```bash
# FastAPI 서버 시작
uvicorn app.main:app --reload

# API 문서: http://localhost:8000/docs
```

### 옵션 3: 완전 자동화 (V1)
- Playwright 자동 업로드 구현
- Celery 스케줄러 설정
- 대시보드 구축

---

## 트러블슈팅

### 크롤링 실패
- 인터넷 연결 확인
- 교보문고 사이트 접속 확인
- Playwright 브라우저 재설치: `playwright install chromium --force`

### DB 오류
- SQLite 파일 삭제 후 재초기화
- `rm coupang_auto.db && python scripts/init_db.py`

### CSV 생성 오류
- `data/uploads/` 폴더 권한 확인
- 폴더 수동 생성: `mkdir -p data/uploads`

---

## 문의

GitHub Issues 또는 PR 환영합니다.
