# 5개 계정 동시 관리 시스템 사용 가이드

## 개요

이 시스템은 쿠팡 판매자센터의 5개 계정을 동시에 관리하고 상품을 자동으로 업로드할 수 있는 기능을 제공합니다.

## 주요 기능

1. **5개 계정 동시 관리**: 계정별 상태 모니터링 및 순차/병렬 업로드
2. **작업 큐 시스템**: 업로드 작업을 큐에 추가하고 관리
3. **드라이런 모드**: 실제 등록 전 시뮬레이션 실행
4. **실시간 모니터링**: 대시보드에서 계정별 상태 확인

## 설정

### 1. 계정 정보 설정

`config/accounts.yaml` 파일을 수정하세요:

```yaml
accounts:
  account_01:
    name: "엄마계정1"
    email: "your_email@example.com"
    password: "your_password"
    enabled: true
    delay_between_products: 15
    delay_between_accounts: 60
```

또는 환경변수 사용:

```yaml
accounts:
  account_01:
    email: "${ACCOUNT1_EMAIL}"
    password: "${ACCOUNT1_PASSWORD}"
```

환경변수 설정 (`.env` 파일):

```env
ACCOUNT1_EMAIL=your_email@example.com
ACCOUNT1_PASSWORD=your_password
ACCOUNT2_EMAIL=...
ACCOUNT2_PASSWORD=...
```

### 2. 상품 데이터 준비

`data/templates/products_to_upload.json` 파일을 생성하세요:

```json
[
  {
    "product_name": "초등 수학 문제집 3학년",
    "sale_price": 15000,
    "original_price": 15000,
    "isbn": "9781234567890",
    "description": "상품 설명",
    "main_image_url": "https://example.com/image.jpg"
  }
]
```

## 사용 방법

### 방법 1: 스크립트 실행

```bash
python scripts/upload_all_accounts.py
```

실행 모드 선택:
- `1`: 순차 실행 (안전, 추천)
- `2`: 병렬 실행 (위험)
- `3`: 드라이런 테스트 (실제 등록 안 함)

### 방법 2: 대시보드 사용

```bash
streamlit run dashboard/pages/3_⬆️_업로드_관리.py
```

또는 메인 대시보드에서:

```bash
streamlit run dashboard/Home.py
```

대시보드에서:
1. 상품 JSON 파일 업로드
2. 대상 계정 선택
3. 실행 옵션 설정 (드라이런, 순차/병렬)
4. 작업 추가 및 실행

### 방법 3: Python 코드에서 직접 사용

```python
from app.services.uploader_service import UploaderService
import asyncio

uploader_service = UploaderService()

products = [
    {
        "product_name": "상품명",
        "sale_price": 15000,
        "original_price": 15000,
        # ...
    }
]

# 모든 계정에 순차 업로드
result = asyncio.run(
    uploader_service.upload_to_all_accounts(
        products=products,
        dry_run=True,  # 드라이런 모드
        execution_mode='sequential'
    )
)
```

## 실행 모드

### 순차 실행 (Sequential)

- 계정1 완료 → 계정2 → 계정3 ...
- 가장 안전한 방식
- 계정 간 60초 딜레이
- 추천: 일일 업로드 제한이 있는 경우

### 병렬 실행 (Parallel)

- 최대 2개 계정 동시 실행
- 위험도 높음 (계정 정지 가능)
- 빠른 업로드 필요 시 사용
- 주의: 쿠팡 정책 위반 가능성

## 안전장치

1. **드라이런 모드**: 실제 등록 전 시뮬레이션
2. **상품 간 딜레이**: 기본 15초
3. **계정 간 딜레이**: 기본 60초
4. **상태 추적**: 모든 작업 로그 저장
5. **실패 처리**: 실패 시 즉시 중단 옵션

## 모니터링

### 계정 상태 확인

```python
from app.services.account_manager import AccountManager

manager = AccountManager()
status = manager.get_account_status_summary()
print(status)
```

### 작업 상태 확인

```python
from app.services.uploader_service import UploaderService

uploader_service = UploaderService()
job_status = uploader_service.get_job_status("job_20240101_120000")
print(job_status)
```

## 파일 구조

```
Coupong/
├── config/
│   └── accounts.yaml          # 계정 설정
├── app/services/
│   ├── account_manager.py     # 계정 관리자
│   ├── job_queue.py           # 작업 큐
│   └── uploader_service.py    # 통합 업로더
├── scripts/
│   └── upload_all_accounts.py # 실행 스크립트
├── dashboard/pages/
│   └── 3_⬆️_업로드_관리.py    # 대시보드
└── data/
    ├── status/
    │   └── account_status.json # 계정 상태
    ├── queue/
    │   └── jobs.json          # 작업 큐
    └── templates/
        └── products_to_upload.json # 상품 데이터
```

## 주의사항

1. **약관 준수**: 쿠팡 판매자 약관을 준수하세요
2. **드라이런 먼저**: 실제 업로드 전 반드시 드라이런 테스트
3. **일일 제한**: 계정별 일일 업로드 제한 확인
4. **비밀번호 보안**: 환경변수나 암호화 사용 권장
5. **로그 확인**: `logs/` 폴더의 로그 파일 정기 확인

## 문제 해결

### 로그인 실패
- 이메일/비밀번호 확인
- CAPTCHA/2FA 수동 처리 필요할 수 있음
- 세션 파일 확인 (`sessions/`)

### 업로드 실패
- 쿠팡 페이지 구조 변경 가능성
- `uploaders/playwright_uploader.py` 수정 필요
- 로그 파일 확인

### 계정 정지
- 병렬 실행 사용 시 위험도 높음
- 딜레이 시간 증가
- 순차 실행으로 전환

## 다음 단계

1. 실제 쿠팡 페이지 구조에 맞게 `PlaywrightUploader` 수정
2. 카테고리 매핑 테이블 생성
3. 이미지 업로드 로직 구현
4. 에러 복구 메커니즘 추가
