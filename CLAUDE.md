# Coupong Project - Claude Code Instructions

## Obsidian 자동 기록 (필수)

이 프로젝트는 `Coupong_vault/`에 개발 기록을 자동으로 남깁니다.
**개발 작업을 수행할 때마다 반드시 Obsidian vault를 업데이트하세요. 사용자가 요청하지 않아도 자동으로 해야 합니다.**

### 언제 기록하는가

- 코드 수정/생성/삭제 후
- 버그 수정 후
- 새 기능 구현 후
- 리팩토링 후
- 설정 변경 후
- 중요한 의사결정을 내린 후

### 기록 방법

**1. 일일 로그 (매 작업 후 필수)**

`Coupong_vault/01-Daily/YYYY-MM-DD.md` 파일에 append:

```markdown
## HH:MM - 작업 제목

- **작업 내용**: 무엇을 했는지 간단 설명
- **변경 파일**: 수정한 파일 목록
- **이유**: 왜 이 변경을 했는지

---
```

파일이 없으면 아래 헤더로 새로 생성:
```markdown
# YYYY년 MM월 DD일 개발 로그

## 오늘의 작업

---
```

**2. 기능 노트 (새 기능 구현 시)**

`Coupong_vault/02-Features/기능명.md`에 기능 문서 작성

**3. 기술 문서 (아키텍처 변경 시)**

`Coupong_vault/03-Technical/문서명.md`에 기술 문서 작성

**4. 의사결정 로그 (중요 결정 시)**

`Coupong_vault/04-Decisions/결정명.md`에 배경, 결정, 대안 기록

**5. 대화 기록 (중요 대화 종료 시 필수)**

아래 조건에 해당하는 대화가 끝날 때, `Coupong_vault/06-Conversations/YYYY-MM-DD-주제.md`에 요약 기록:

기록 대상:
- 새 기능 설계/구현을 논의한 대화
- 복잡한 버그를 해결한 대화
- 아키텍처나 설계 결정을 내린 대화
- 여러 파일을 수정하는 큰 작업을 진행한 대화

기록하지 않는 대화:
- 단순 질문/답변 (1-2턴)
- 파일 내용 확인만 한 대화
- 오타 수정 등 사소한 변경

작성 형식:
```markdown
# Claude와의 대화 - [주제]

#conversation #[태그]

**날짜:** YYYY-MM-DD
**주제:** 대화 주제 한 줄 요약

---

## 대화 개요
2-3줄로 무엇을 논의/작업했는지 요약

## 진행 과정
1. [첫 번째 단계]
2. [두 번째 단계]
...

## 주요 결정/결과
- 결정 사항이나 작업 결과물 목록

## 변경된 파일
- `경로/파일.py` - 변경 내용

## 관련 문서
- [[관련-문서]]
```

주의:
- 같은 날 같은 주제면 기존 파일에 append
- 다른 주제면 새 파일 생성
- `06-Conversations/README.md`의 대화 목록도 업데이트

### 주의사항

- 일일 로그는 **append** (기존 내용 뒤에 추가). 절대 덮어쓰지 마세요
- 시간 형식: `HH:MM` (24시간제)
- 한국어로 작성
- 간결하게 (3-5줄 이내로 요약)
- 코드 블록은 짧게 핵심만

### Python 로거 사용 가능

`obsidian_logger.py`의 `ObsidianLogger` 클래스도 사용 가능:
```python
from obsidian_logger import ObsidianLogger
logger = ObsidianLogger()
logger.log_to_daily("내용", "제목")
logger.log_feature("기능명", "설명")
logger.log_decision("결정명", "배경", "결정")
logger.log_bug("버그명", "설명", "해결방법")
```

## 프로젝트 개요

- 쿠팡 도서 판매 자동화 시스템
- 알라딘 API -> 마진 분석 -> 묶음 SKU -> 쿠팡 CSV 생성/업로드
- Python 3.10+, SQLAlchemy, SQLite
- DB: `coupang_auto.db`

## 문서 템플릿

Feature/Technical 문서 작성 시 아래 구조를 따르세요:

```markdown
# 기능명

#feature #태그

**상태:** ✅ 완료 / ⏳ 진행중 / ❌ 미구현
**구현 파일:** `경로/파일.py`

---

## 개요
2-3줄 요약

## 구현 파일
파일 경로 + 핵심 클래스/메서드

## 핵심 로직
코드에서 추출한 실제 동작 방식

## 관련 문서
- [[관련-문서]] - 설명
```

## 코드 규칙

- 한국어 주석
- UTF-8 인코딩 필수 (`encoding='utf-8'`)
- 기존 코드 스타일 따르기
