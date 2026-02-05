"""
Claude Code Stop hook - 개발 변경사항을 Obsidian daily note에 자동 기록

Claude가 응답을 마칠 때마다 실행되어 파일 변경사항을 감지하고 기록합니다.
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
VAULT_PATH = PROJECT_ROOT / "obsidian_vault"
DAILY_DIR = VAULT_PATH / "01-Daily"

# 무시할 경로 패턴
IGNORE_PATTERNS = [
    "obsidian_vault/",
    ".claude/",
    ".git/",
    "__pycache__/",
    ".pyc",
    "CLAUDE.md",
]


def get_unstaged_changes():
    """git diff로 변경된 파일 목록 가져오기"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(PROJECT_ROOT), timeout=10
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]

        # staged 변경사항도 확인
        result2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(PROJECT_ROOT), timeout=10
        )
        staged = [f.strip() for f in result2.stdout.strip().split("\n") if f.strip()]

        all_files = list(set(files + staged))

        # 무시 패턴 필터링
        filtered = []
        for f in all_files:
            if not any(pat in f for pat in IGNORE_PATTERNS):
                filtered.append(f)

        return filtered
    except Exception:
        return []


def get_daily_note_path():
    """오늘의 daily note 경로"""
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return DAILY_DIR / f"{today}.md"


def ensure_daily_header(note_path):
    """daily note 헤더가 없으면 생성"""
    if not note_path.exists():
        now = datetime.now()
        header = f"# {now.strftime('%Y년 %m월 %d일')} 개발 로그\n\n## 오늘의 작업\n\n---\n"
        note_path.write_text(header, encoding="utf-8")


def already_logged_recently(note_path, files):
    """최근 5분 내에 같은 파일이 기록됐는지 확인 (중복 방지)"""
    if not note_path.exists():
        return False

    try:
        content = note_path.read_text(encoding="utf-8")
        # 마지막 500자만 확인
        recent = content[-500:]

        # 모든 파일이 이미 최근에 기록됐으면 스킵
        for f in files:
            if f not in recent:
                return False
        return True
    except Exception:
        return False


def log_changes(files):
    """변경된 파일들을 daily note에 기록"""
    if not files:
        return

    note_path = get_daily_note_path()
    ensure_daily_header(note_path)

    # 중복 방지
    if already_logged_recently(note_path, files):
        return

    now = datetime.now().strftime("%H:%M")

    files_list = "\n".join([f"  - `{f}`" for f in files[:10]])
    if len(files) > 10:
        files_list += f"\n  - ... 외 {len(files) - 10}개"

    entry = f"\n### {now} - [Auto] 파일 변경 감지\n\n**변경 파일:** ({len(files)}개)\n{files_list}\n\n"

    with open(note_path, "a", encoding="utf-8") as f:
        f.write(entry)


def main():
    """메인 hook 핸들러"""
    try:
        # stdin에서 hook 데이터 읽기
        stdin_data = sys.stdin.read()
        if stdin_data:
            data = json.loads(stdin_data)
        else:
            data = {}
    except Exception:
        data = {}

    # 변경된 파일 확인
    changed_files = get_unstaged_changes()

    if changed_files:
        log_changes(changed_files)


if __name__ == "__main__":
    main()
