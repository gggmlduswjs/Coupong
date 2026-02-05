# Claude Code + Obsidian 개발 워크플로우

#obsidian #claude #integration

**마지막 업데이트:** 2026-02-05

---

## 개요

이 프로젝트는 **Claude Code**(CLI)로 개발하고, **Obsidian vault**에 자동으로 개발 기록을 남기는 워크플로우를 사용한다.

```
┌─────────────────┐
│  Claude Code    │  코딩 + 개발
│  (CLI Agent)    │
└────────┬────────┘
         │ CLAUDE.md 지시에 따라
         │ 자동으로 Obsidian 문서 업데이트
         ↓
┌─────────────────┐
│  Obsidian Vault │  개발 기록 + 문서화
│  obsidian_vault/│
└────────┬────────┘
         │ 개발자가 Obsidian 앱에서
         │ 문서 탐색 + 검토
         ↓
┌─────────────────┐
│  개발자 검토    │  문맥 파악 → 다음 지시
└─────────────────┘
```

---

## 핵심 메커니즘: CLAUDE.md

`CLAUDE.md` 파일이 Claude Code에게 다음을 지시:

1. **코드 변경 후** → `01-Daily/YYYY-MM-DD.md`에 작업 로그 append
2. **새 기능 구현 시** → `02-Features/기능명.md` 생성/업데이트
3. **아키텍처 변경 시** → `03-Technical/문서명.md` 업데이트
4. **중요 결정 시** → `04-Decisions/결정명.md` 기록

이렇게 하면 코드 변경과 문서화가 **동시에** 이루어진다.

---

## Vault 구조

```
obsidian_vault/
├── 00-Index/           현황 + 목차
│   ├── Dashboard.md    전체 진행률 + 5계정 현황
│   ├── Index.md        문서 목차 + 빠른 시작
│   └── Development-Timeline.md  Phase 1~4 타임라인
│
├── 01-Daily/           일일 개발 로그 (append only)
│   └── 2026-02-05.md
│
├── 02-Features/        기능별 상세 문서
│   ├── 쿠팡-API-연동.md        ★ WING API 전체 문서
│   ├── Database-Schema-V2.md    DB 8개 테이블
│   ├── 알라딘-API-크롤러.md     도서 수집
│   ├── 마진-계산기.md           마진 분석
│   ├── 묶음-SKU-생성기.md       저마진 도서 묶음
│   └── 연도-추출.md             제목 연도 추출
│
├── 03-Technical/       기술 문서
│   ├── 시스템-아키텍처.md       전체 구조도
│   ├── 파일-구조.md             디렉토리 + 파일 역할
│   ├── Tech-Stack.md            기술 스택
│   ├── 사용-가이드.md           파이프라인 실행법
│   └── 설정-가이드.md           환경변수 + API 키 설정
│
└── 04-Decisions/       의사결정 기록
    ├── 통계-계산-방식.md
    └── 코드-정리-계획.md
```

---

## 프로젝트 이해를 위한 문서 읽는 순서

처음 프로젝트를 파악할 때 이 순서로 읽으면 된다:

1. **[[Dashboard]]** - 전체 진행률, 5계정 현황, 구현 파일 맵
2. **[[시스템-아키텍처]]** - 전체 구조도 + 데이터 흐름
3. **[[Development-Timeline]]** - Phase별 진행 상황
4. **[[파일-구조]]** - 어떤 파일이 어디 있는지
5. **[[쿠팡-API-연동]]** - 현재 핵심 기능 (WING API)
6. **[[Database-Schema-V2]]** - DB 테이블 구조
7. **[[사용-가이드]]** - 실제 실행 방법

---

## 일일 로그 작성 규칙

`01-Daily/YYYY-MM-DD.md` 파일 형식:

```markdown
# YYYY년 MM월 DD일 개발 로그

## 오늘의 작업

---

## HH:MM - 작업 제목

- **작업 내용**: 무엇을 했는지
- **변경 파일**: 수정한 파일 목록
- **이유**: 왜 이 변경을 했는지

---
```

규칙:
- **append only** - 절대 기존 내용 덮어쓰지 않음
- 24시간제 시간 형식 (`HH:MM`)
- 한국어 작성, 간결하게 (3-5줄)

---

## Python 로거 (선택사항)

코드에서 직접 Obsidian에 기록할 수도 있다:

```python
from obsidian_logger import ObsidianLogger

logger = ObsidianLogger()

# 일일 로그
logger.log_to_daily("WING API 동기화 완료", "상품 동기화")

# 기능 문서
logger.log_feature("카테고리 추천", "상품명 기반 동적 카테고리 추천")

# 버그 기록
logger.log_bug("HMAC 서명 오류", "쿼리 파라미터 정렬 문제", "정렬 제거로 해결")

# 의사결정
logger.log_decision("API vs CSV", "속도와 자동화", "WING API 직접 등록 채택")
```

---

## Obsidian 앱에서 활용 (선택사항)

Obsidian 앱을 설치하면 문서를 더 편하게 탐색할 수 있다:

### 설치
```
https://obsidian.md/download
→ "Open folder as vault" 선택
→ C:\Users\MSI\Desktop\Coupong\obsidian_vault
```

### 유용한 기능
- **백링크**: `[[문서명]]`으로 문서 간 연결 자동 추적
- **그래프 뷰**: 문서 관계를 시각적으로 탐색
- **검색**: Ctrl+Shift+F로 전체 문서 검색

### 추천 플러그인
- **Dataview**: 동적 쿼리 (예: 미완료 기능 목록)
- **Calendar**: 일일 로그를 달력으로 탐색

---

## 관련 문서

- [[Index]] - 전체 문서 목차
- [[Dashboard]] - 진행률 + 기능 상태
- [[Development-Timeline]] - 개발 타임라인
