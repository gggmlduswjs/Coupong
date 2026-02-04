# 🚀 쿠팡 자동 업로드 가이드

## 📋 개요

5개 계정에 자동으로 상품을 업로드하는 시스템입니다.

---

## ✅ 준비사항

### 1. 계정 등록 확인
```bash
python scripts/register_accounts.py
```

**등록된 계정:**
- account_1: 007-book
- account_2: 007-ez
- account_3: 007-bm
- account_4: 002-bm
- account_5: big6ceo

### 2. 상품 데이터 확인
```bash
# DB에 상품이 있는지 확인
python scripts/test_system.py
```

---

## 🎯 사용 방법

### 옵션 1: 단일 계정 테스트

```bash
python uploaders/coupang_auto_uploader.py
```

**동작:**
1. 첫 번째 계정으로 로그인
2. 테스트 상품 1개 업로드

### 옵션 2: 전체 계정 일괄 업로드

```bash
python scripts/auto_upload_all.py
```

**동작:**
1. 5개 계정 순회
2. 각 계정에 상품 업로드 (최대 5개)
3. 계정 간 30초 대기

---

## 🔧 작동 방식

### 1. 로그인 프로세스
```
1. 쿠팡 판매자센터 접속
2. 이메일/비밀번호 자동 입력
3. 로그인 버튼 클릭
4. 세션 저장 (sessions/account_X.json)
```

### 2. 업로드 프로세스

#### 방법 A: ISBN 카탈로그 등록 (도서 전용)
```
1. ISBN으로 상품 검색
2. 쿠팡 카탈로그에서 선택
3. 가격/재고만 입력
4. 등록 완료
```

#### 방법 B: 수동 폼 등록
```
1. 상품명, 가격, 카테고리 입력
2. 이미지 업로드
3. 상세 설명 입력
4. 등록 완료
```

---

## ⚠️ 주의사항

### CAPTCHA / 2FA
- **CAPTCHA가 나오면:** 수동으로 풀어야 함
- **2단계 인증:** SMS 코드 입력 필요
- 스크립트가 30초 대기하므로 그동안 처리

### 세션 관리
- 한 번 로그인하면 세션 저장
- 다음번엔 로그인 없이 바로 업로드 가능
- 세션 유효기간: 약 7일

### 속도 제한
```python
UPLOAD_DELAY_MIN = 10초
UPLOAD_DELAY_MAX = 20초
UPLOAD_MAX_DAILY = 20개/계정
```

**하루 제한:**
- 계정당 20개 상품
- 5개 계정 = 총 100개 가능

---

## 📊 실행 예시

### 단일 계정 테스트
```
Coupang Auto Uploader - Test
============================================================

Step 1: Login...
[12:34:56] INFO - Logging in: account_1 (007-book)
[12:34:58] INFO - Login button clicked
[12:35:03] INFO - Login successful!
[12:35:03] INFO - Session saved: sessions/account_1.json
✓ Login successful

Step 2: Upload product...
[12:35:05] INFO - Uploading product: 초등 수학 문제집 3학년 [10% Discount]
[12:35:06] INFO - Trying catalog registration with ISBN: 9788956746425
[12:35:12] INFO - Product uploaded successfully!
✓ Upload successful: Catalog registration succeeded
```

### 전체 계정 업로드
```
============================================================
Account 1/5: account_1
============================================================
[12:40:01] INFO - Logging in: 007-book
[12:40:05] INFO - Login successful!
[12:40:05] INFO - Uploading 5 products...
[12:40:15] INFO - Waiting 15.3 seconds before next upload...
[12:40:30] INFO - Upload complete: 5/5 successful
[12:40:30] INFO - Waiting 30 seconds before next account...

============================================================
Account 2/5: account_2
============================================================
...
```

---

## 🐛 트러블슈팅

### 문제 1: 로그인 실패
**증상:** "Login failed" 또는 계속 로그인 페이지
**해결:**
1. 계정 정보 확인: `python scripts/register_accounts.py`
2. 수동 로그인 테스트: 브라우저에서 직접 로그인
3. CAPTCHA 풀기

### 문제 2: 세션 만료
**증상:** "No session file" 또는 "Session expired"
**해결:**
```bash
# 세션 파일 삭제 후 재로그인
rm sessions/account_*.json
python uploaders/coupang_auto_uploader.py
```

### 문제 3: 업로드 실패
**증상:** "Upload failed" 또는 "Form not found"
**해결:**
1. 쿠팡 페이지 구조 변경 가능성
2. 수동으로 한 번 등록해보고 프로세스 확인
3. 스크립트 수정 필요할 수 있음

### 문제 4: 계정 정지
**증상:** "계정이 차단되었습니다"
**해결:**
- 너무 빠른 업로드 → 속도 느추기
- 하루 제한 초과 → 다음 날 재시도
- 쿠팡 고객센터 문의

---

## 🔐 보안

### 세션 파일 위치
```
sessions/
├── account_1.json
├── account_2.json
├── account_3.json
├── account_4.json
└── account_5.json
```

**주의:**
- ❌ 세션 파일을 Git에 커밋 금지
- ❌ 다른 사람과 공유 금지
- ✅ `.gitignore`에 자동 제외됨

---

## 📈 성공률 향상 팁

### 1. 시간대 선택
- **추천:** 새벽 2~6시 (서버 한가)
- **비추천:** 오전 10~12시 (피크 타임)

### 2. 계정별 간격
- 최소 30분 간격
- 같은 IP에서 5개 계정 동시 사용 주의

### 3. 상품 정보 품질
- 상품명: 키워드 최적화
- 이미지: 고화질 (최소 500x500)
- 설명: 상세하게 작성

### 4. 세션 재사용
- 매번 로그인 대신 세션 재사용
- 로그인 횟수 줄여서 보안 경고 방지

---

## 📝 다음 단계

### Phase 1 (현재)
- ✅ 로그인 자동화
- ✅ 세션 저장
- 🔧 업로드 자동화 (테스트 필요)

### Phase 2 (개선)
- [ ] 이미지 자동 업로드
- [ ] 카테고리 자동 선택
- [ ] 에러 자동 재시도
- [ ] 업로드 결과 DB 저장

### Phase 3 (고도화)
- [ ] 스케줄러 (매일 자동 실행)
- [ ] 성공률 통계
- [ ] 실패 원인 분석
- [ ] 자동 재업로드

---

## 💬 FAQ

**Q: 한 번에 몇 개까지 업로드 가능한가요?**
A: 계정당 하루 20개 권장. 5개 계정 = 총 100개/일

**Q: CAPTCHA는 자동으로 풀리나요?**
A: 아니요. 수동으로 풀어야 합니다.

**Q: 실패하면 자동으로 재시도하나요?**
A: 현재는 안 됩니다. Phase 2에서 추가 예정.

**Q: 쿠팡에서 자동화를 금지하나요?**
A: 명시적 금지는 없으나, 과도한 자동화는 계정 정지 가능성.

**Q: 세션은 얼마나 유지되나요?**
A: 약 7일. 만료되면 재로그인 필요.

---

## 🚀 바로 시작하기

```bash
# 1. 테스트 (1개 계정, 1개 상품)
python uploaders/coupang_auto_uploader.py

# 2. 전체 업로드 (5개 계정)
python scripts/auto_upload_all.py
```

**첫 실행 시:**
- 브라우저가 열립니다
- 로그인 정보 자동 입력
- CAPTCHA가 나오면 수동으로 풀기
- 이후엔 자동으로 진행

---

**🎉 이제 쿠팡 자동 업로드를 시작하세요!**
