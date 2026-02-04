# 5개 계정 동시 관리 시스템 구현 완료

## 구현된 기능

### ✅ 완료된 항목

1. **계정 관리자 (AccountManager)**
   - 5개 계정 순차/병렬 업로드 관리
   - 계정별 상태 추적 및 저장
   - 실패 처리 및 재시도 로직

2. **작업 큐 시스템 (JobQueue)**
   - 업로드 작업 대기열 관리
   - 작업 상태 추적 (pending, running, completed, failed)
   - 작업 이력 저장

3. **통합 업로더 서비스 (UploaderService)**
   - 계정 관리자와 작업 큐 통합
   - 간편한 업로드 API 제공
   - 작업 생성 및 실행 관리

4. **계정 설정 파일 (config/accounts.yaml)**
   - 5개 계정 설정 템플릿
   - 환경변수 지원
   - 딜레이 설정

5. **대시보드 페이지**
   - 실시간 계정 상태 모니터링
   - 업로드 작업 큐 관리
   - 새 작업 생성 UI

6. **실행 스크립트**
   - `scripts/upload_all_accounts.py`: CLI 실행 스크립트
   - `scripts/quick_upload_example.py`: 빠른 예시 스크립트

## 파일 구조

```
Coupong/
├── config/
│   └── accounts.yaml                    # 계정 설정
├── app/services/
│   ├── __init__.py
│   ├── account_manager.py              # 계정 관리자
│   ├── job_queue.py                    # 작업 큐
│   └── uploader_service.py             # 통합 업로더
├── scripts/
│   ├── upload_all_accounts.py          # 메인 실행 스크립트
│   └── quick_upload_example.py         # 예시 스크립트
├── dashboard/pages/
│   └── 3_⬆️_업로드_관리.py            # 대시보드 페이지
├── data/
│   ├── status/
│   │   └── account_status.json         # 계정 상태 (자동 생성)
│   ├── queue/
│   │   └── jobs.json                   # 작업 큐 (자동 생성)
│   └── templates/
│       └── products_to_upload.json.example  # 상품 템플릿 예시
└── README_MULTI_ACCOUNT.md             # 사용 가이드
```

## 사용 방법

### 1. 설정

`config/accounts.yaml` 파일 수정:

```yaml
accounts:
  account_01:
    email: "your_email@example.com"
    password: "your_password"
    enabled: true
```

### 2. 상품 데이터 준비

`data/templates/products_to_upload.json` 생성:

```json
[
  {
    "product_name": "상품명",
    "sale_price": 15000,
    "original_price": 15000,
    "isbn": "9781234567890",
    "description": "상품 설명",
    "main_image_url": "https://..."
  }
]
```

### 3. 실행

#### 방법 1: 스크립트 실행
```bash
python scripts/upload_all_accounts.py
```

#### 방법 2: 대시보드
```bash
streamlit run dashboard/pages/3_⬆️_업로드_관리.py
```

#### 방법 3: Python 코드
```python
from app.services.uploader_service import UploaderService
import asyncio

uploader_service = UploaderService()
result = asyncio.run(
    uploader_service.upload_to_all_accounts(
        products=[...],
        dry_run=True,
        execution_mode='sequential'
    )
)
```

## 주요 기능

### 순차 실행 (Sequential)
- 계정1 → 계정2 → 계정3 ... 순서대로 실행
- 가장 안전한 방식
- 계정 간 60초 딜레이

### 병렬 실행 (Parallel)
- 최대 2개 계정 동시 실행
- 빠르지만 위험도 높음
- 주의 필요

### 드라이런 모드
- 실제 등록 없이 시뮬레이션
- 테스트용으로 안전

## 다음 단계

1. **실제 쿠팡 페이지 구조에 맞게 수정**
   - `uploaders/playwright_uploader.py`의 셀렉터 수정
   - 카테고리 선택 로직 구현
   - 이미지 업로드 로직 구현

2. **비밀번호 암호화**
   - `app/utils/encryption.py` 활용
   - 계정 정보 안전하게 저장

3. **에러 복구**
   - 실패한 상품 자동 재시도
   - 부분 실패 시 롤백

4. **모니터링 강화**
   - 이메일/카카오 알림
   - 실시간 대시보드 개선

## 주의사항

⚠️ **중요**: 
- 실제 쿠팡 페이지 구조에 맞게 `PlaywrightUploader` 수정 필요
- 드라이런 모드로 먼저 테스트
- 쿠팡 약관 준수 필수
- 계정 정지 위험 고려

## 문제 해결

### 로그인 실패
- 이메일/비밀번호 확인
- CAPTCHA/2FA 수동 처리 필요

### 업로드 실패
- 쿠팡 페이지 구조 변경 가능
- `uploaders/playwright_uploader.py` 수정 필요

### 계정 정지
- 병렬 실행 사용 시 위험
- 순차 실행으로 전환 권장
