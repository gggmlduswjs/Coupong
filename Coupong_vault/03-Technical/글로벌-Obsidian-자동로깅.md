# 글로벌 Obsidian 자동 로깅 시스템

#technical #obsidian #automation

**상태:** ✅ 완료
**구현 파일:** `~/.claude/scripts/obsidian_auto_log.py`, `~/.claude/scripts/init_vault.py`

---

## 개요

모든 프로젝트에서 Claude Code 사용 시 `{프로젝트명}_vault/`에 개발 기록이 자동으로 남는 시스템.
vault가 없는 프로젝트에서는 아무 영향 없이 무시됨.

## 파일 구조

```
~/.claude/                          ← 글로벌 (어떤 PC든 동일)
├── CLAUDE.md                       ← 글로벌 지시사항
├── settings.json                   ← 글로벌 Stop hook
└── scripts/
    ├── obsidian_auto_log.py        ← Stop hook 스크립트 (범용)
    └── init_vault.py               ← 새 프로젝트 vault 초기화

Coupong/                            ← 프로젝트별
├── scripts/
│   └── install_global_hooks.py     ← 다른 PC 설치 스크립트
└── Coupong_vault/                  ← Obsidian vault
    ├── 00-Index/
    ├── 01-Daily/                   ← 자동 기록 위치
    ├── 02-Features/
    ├── 03-Technical/
    ├── 04-Decisions/
    └── 06-Conversations/
```

## 다른 PC 설치 (한 번만)

```bash
# 1. 프로젝트 clone
git clone <repo-url> && cd Coupong

# 2. 글로벌 hook 설치
python scripts/install_global_hooks.py

# 끝! 이후 모든 프로젝트에서 자동 동작
```

설치 스크립트가 하는 일:
- `~/.claude/scripts/obsidian_auto_log.py` 생성 (없을 때만)
- `~/.claude/scripts/init_vault.py` 생성 (없을 때만)
- `~/.claude/CLAUDE.md` 생성 (없을 때만)
- `~/.claude/settings.json`에 Stop hook 추가 (없을 때만)
- hook 경로는 `Path.home()` 기반 → **OS/사용자명 무관하게 동작**

## 평소 사용법

### 기존 프로젝트 (vault 있음)

**아무것도 안 해도 됨.** Claude Code 대화가 끝날 때마다 자동 기록.

### 새 프로젝트에서 vault 만들기

```bash
cd ~/Desktop/새프로젝트
python ~/.claude/scripts/init_vault.py
```

실행하면 생성되는 구조 (예: `MyApp` 프로젝트):
```
MyApp_vault/
├── 00-Index/        ← Dashboard.md, Index.md
├── 01-Daily/        ← 일일 로그 (자동 기록)
├── 02-Features/     ← 기능 문서
├── 03-Technical/    ← 기술 문서
├── 04-Decisions/    ← 의사결정 기록
└── 06-Conversations/ ← Claude 대화 기록
```

`.gitignore`에 `MyApp_vault/.obsidian/` 자동 추가됨.

### vault 없는 프로젝트

hook 실행 → vault 없음 감지 → 즉시 종료 (에러 없음, 영향 없음)

## 자동 기록 동작 방식

1. Claude Code 대화 종료 (Stop 이벤트)
2. 글로벌 Stop hook이 `obsidian_auto_log.py` 실행
3. `git rev-parse --show-toplevel`로 프로젝트 루트 감지
4. `{프로젝트명}_vault/` 존재 확인 → 없으면 종료
5. `git diff --name-only` + `git diff --cached --name-only`로 변경 파일 수집
6. 무시 패턴 필터링 (`_vault/`, `.claude/`, `.git/`, `__pycache__`, `CLAUDE.md`)
7. `git diff`로 파일별 +/-줄 수 통계 + 주요 추가 라인 추출
8. `{프로젝트명}_vault/01-Daily/YYYY-MM-DD.md`에 append
9. 중복 방지: 마지막 800자 내에 동일 파일명 있으면 스킵

## hook 명령어 (이식성)

```json
"command": "python -c \"from pathlib import Path; exec(Path.home().joinpath('.claude/scripts/obsidian_auto_log.py').read_text())\""
```

`Path.home()` 사용으로 절대경로 하드코딩 없음 → Windows/Mac/Linux 어디서든 동작.

## 기록 예시

```markdown
### 19:26 - [Auto] 코드 변경 감지 (Coupong)

**변경 파일:** (3개, +45 / -12)
  - `app/models/account.py` (+14/-1)
  - `app/constants.py` (+26/-8)
  - `scripts/run_pipeline.py` (+5/-3)

**주요 추가 내용:**
  - `vendor_id = Column(String(20), nullable=True)`
  - `COUPANG_WING_RATE_LIMIT = 0.1`

---
```

## Coupong 프로젝트 특이사항

- vault 이름: `Coupong_vault/` (프로젝트명 기반)
- `.claude/settings.local.json`에 Stop hook 없음 (글로벌이 대체)
- PostToolUse prompt hook은 유지 (Write/Edit 시 즉시 daily note 기록 유도)
- 기존 `scripts/obsidian_hook.py`는 삭제됨 (글로벌 스크립트로 대체)

## 관련 문서

- [[사용-가이드]] - 프로젝트 사용법
- [[시스템-아키텍처]] - 전체 시스템 구조
