# Obsidian 실시간 개발 로깅 가이드

## 🎯 개요

개발 과정을 자동으로 Obsidian에 기록하여:
- 📝 실시간 개발 진행 상황 추적
- 🔗 기능/문서/의사결정 간 백링크 연결
- 📊 타임라인 자동 생성
- 🔍 빠른 검색 및 회고

---

## 🚀 시작하기

### 1단계: Vault 초기화

```bash
python obsidian_logger.py
```

생성되는 폴더 구조:
```
obsidian_vault/
├── 00-Index/              # 메인 대시보드
│   ├── Index.md
│   └── Development-Timeline.md
├── 01-Daily/              # 일일 개발 로그
│   └── 2026-02-05.md
├── 02-Features/           # 기능별 문서
│   ├── Database-Schema-V2.md
│   ├── 연도-추출.md
│   └── 마진-계산기.md
├── 03-Technical/          # 기술 문서
│   └── Tech-Stack.md
├── 04-Decisions/          # 의사결정 로그
├── 05-Tasks/              # 작업 추적
└── 06-Database/           # DB 스키마
```

### 2단계: Obsidian에서 Vault 열기

1. Obsidian 실행
2. "Open folder as vault" 선택
3. `C:\Users\MSI\Desktop\Coupong\obsidian_vault` 선택

---

## 📝 사용 방법

### Python 코드에서 로깅

```python
from obsidian_logger import ObsidianLogger

logger = ObsidianLogger()

# 1. 기능 개발 시작
logger.log_feature(
    "새 기능 이름",
    "기능 설명",
    tags=["feature", "api"],
    status="진행중"
)

# 2. 일일 로그
logger.log_to_daily(
    "오늘 작업한 내용...",
    title="작업 제목"
)

# 3. 의사결정 기록
logger.log_decision(
    "DB 스키마 변경",
    context="기존 스키마로는 중복 방지 불가",
    decision="UNIQUE 제약조건 추가",
    alternatives=["애플리케이션 레벨 체크", "트리거 사용"]
)

# 4. 버그 수정
logger.log_bug(
    "연도 추출 오류",
    "2자리 연도 변환 실패",
    solution="정규식 패턴 수정"
)

# 5. 기술 문서
logger.log_technical(
    "마진 계산 공식",
    """
    ## 공식
    순마진 = 판매가 - 공급가 - 쿠팡수수료 - 배송비

    ## 예시
    ...
    """,
    tags=["calculator", "formula"]
)
```

---

## 🔗 Obsidian 기능 활용

### 백링크
```markdown
이 기능은 [[Database Schema V2]]에 의존합니다.
[[마진 계산기]]를 먼저 구현해야 합니다.
```

### 태그
```markdown
#feature #database #completed
#bug #urgent
#decision #architecture
```

### 데이터뷰 (플러그인)
```dataview
TABLE status, tags
FROM "02-Features"
WHERE status = "완료"
```

### 그래프 뷰
- 노트 간 연결 시각화
- 기능 의존성 파악
- 개발 흐름 추적

---

## 📊 자동 생성되는 문서

### 1. 일일 노트 (01-Daily/)

**예시: 2026-02-05.md**
```markdown
# 2026년 02월 05일 개발 로그

## 📊 오늘의 작업

---

## 09:30 - 시스템 시작

Obsidian 연동 시작! 🚀

---

## 10:15 - Feature: Database Schema V2

**Database Schema V2** 작업
- 상태: 완료
- 8개 테이블, 중복 방지 제약조건

---

## 11:30 - Feature: 연도 추출

**연도 추출** 작업
- 상태: 완료
- 정규식 기반, 87% 성공률

---
```

### 2. 기능 노트 (02-Features/)

**예시: 마진-계산기.md**
```markdown
# 마진 계산기

#feature #calculator

**상태:** 완료
**작성일:** 2026-02-05 10:30

---

## 개요

출판사별 공급률 기반 수익성 자동 판단
배송 정책 자동 결정

## 구현 내역

- Publisher.calculate_margin() 메서드
- 도서정가제 준수 (정가 × 0.9)
- 배송비 고려 순마진 계산

## 관련 파일

- app/models/publisher.py
- analyzers/margin_calculator.py

## 관련 노트

- [[Database Schema V2]]
- [[출판사 관리]]

---
```

### 3. 개발 타임라인

자동으로 업데이트되는 타임라인:
```markdown
## 2026-02-05

### ✅ 완료
- Database V2 스키마
- 연도 추출 (87% 성공률)
- 마진 계산기
- 묶음 SKU 생성기

### 🚧 진행 중
- Obsidian 연동

### ⏳ 계획
- 판매 분석 엔진
- 대시보드
```

---

## 🎨 고급 활용

### 1. 템플릿 사용

**templates/feature-template.md**
```markdown
# {{title}}

#feature

**상태:** 진행중
**담당:**
**시작일:** {{date}}

---

## 목표

## 요구사항

## 구현 계획

## 테스트 계획

## 관련 노트
- [[Index]]
```

### 2. 데일리 노트 자동화

Obsidian 설정:
- Daily notes 플러그인 활성화
- 템플릿 폴더: `templates/`
- 일일 노트 위치: `01-Daily/`
- 형식: `YYYY-MM-DD`

### 3. 태그 활용

자주 쓰는 태그:
- `#feature` - 새 기능
- `#bug` - 버그
- `#refactor` - 리팩토링
- `#test` - 테스트
- `#docs` - 문서화
- `#urgent` - 긴급
- `#completed` - 완료
- `#blocked` - 블로킹

---

## 📊 권장 워크플로우

### 아침 (개발 시작)
```python
logger = ObsidianLogger()
logger.log_to_daily("오늘의 목표:\n- 기능 A 구현\n- 버그 B 수정", "오늘의 계획")
```

### 개발 중 (실시간)
```python
# 기능 개발 시작
logger.log_feature("기능 A", "설명...", status="진행중")

# 중요한 결정
logger.log_decision("제목", "배경", "결정")

# 버그 발견 및 수정
logger.log_bug("버그 제목", "설명", "해결법")
```

### 저녁 (회고)
```python
logger.log_to_daily("""
## 오늘의 성과
- 기능 A 완료
- 버그 B 수정

## 내일 할 일
- 기능 C 시작
- 테스트 작성
""", "일일 회고")
```

---

## 🔍 검색 팁

### Obsidian 내장 검색
- `Ctrl+Shift+F`: 전체 검색
- `tag:#feature`: 태그로 검색
- `file:마진`: 파일명 검색

### 정규식 검색
```
/순마진.*원/
/\d{4}-\d{2}-\d{2}/  # 날짜
```

### 백링크 탐색
- 노트에서 백링크 패널 열기
- 연결된 모든 노트 확인
- 그래프 뷰로 시각화

---

## 💡 실전 예시

### 예시 1: 새 기능 개발

```python
from obsidian_logger import ObsidianLogger

logger = ObsidianLogger()

# 1. 기능 시작
logger.log_feature(
    "CSV 생성기",
    "쿠팡 공식 템플릿 66컬럼 지원",
    tags=["feature", "csv", "uploader"],
    status="진행중"
)

# 2. 개발 중 로그
logger.log_to_daily("CoupangCSVGenerator 클래스 구현 시작")

# 3. 의사결정
logger.log_decision(
    "CSV 라이브러리 선택",
    "pandas vs csv 모듈",
    "csv 모듈 사용 (의존성 최소화)",
    alternatives=["pandas (편리하지만 무거움)", "csv 모듈 (가볍지만 수동 작업)"]
)

# 4. 완료
logger.log_to_daily("CSV 생성기 구현 완료, 테스트 통과", "CSV 생성기 완료")
logger.log_feature("CSV 생성기", "구현 및 테스트 완료", status="완료")
```

### 예시 2: 버그 수정

```python
# 버그 발견
logger.log_bug(
    "연도 추출 실패: 2자리 연도",
    """
    증상: "EBS 24년" → None
    원인: 정규식 패턴 미흡
    """,
    solution="""
    정규식 수정:
    r'[^\d]([2][0-9])(?:년|학년도)?'
    → 2000 + year_suffix 변환
    """
)

logger.log_to_daily("연도 추출 버그 수정, 테스트 통과", "🐛 Bug Fix")
```

---

## 🎯 효과

### Before (Obsidian 없이)
- 개발 기록 분산 (코드, 문서, 메모)
- 의사결정 이유 망각
- 과거 작업 추적 어려움
- 문서 최신화 안됨

### After (Obsidian 연동)
- ✅ 모든 기록 한 곳에
- ✅ 백링크로 연결 관계 자동
- ✅ 타임라인 자동 생성
- ✅ 검색으로 빠른 회고
- ✅ 실시간 문서화

---

## 📌 다음 단계

1. **Obsidian 설치**
   ```
   https://obsidian.md/download
   ```

2. **Vault 열기**
   ```
   C:\Users\MSI\Desktop\Coupong\obsidian_vault
   ```

3. **개발하면서 로깅**
   ```python
   from obsidian_logger import ObsidianLogger
   logger = ObsidianLogger()
   logger.log_to_daily("개발 시작!")
   ```

4. **Obsidian에서 확인**
   - Graph view로 연결 확인
   - 일일 노트에서 진행 상황
   - 태그로 필터링

---

**이제부터 모든 개발이 자동으로 기록됩니다! 📝✨**
