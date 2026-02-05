"""
글로벌 Obsidian 자동 로깅 설치 스크립트

다른 PC에서 한 번만 실행하면 됩니다:
    python scripts/install_global_hooks.py

설치 내용:
    ~/.claude/scripts/obsidian_auto_log.py  (Stop hook)
    ~/.claude/scripts/init_vault.py         (vault 초기화)
    ~/.claude/CLAUDE.md                     (글로벌 지시사항)
    ~/.claude/settings.json                 (글로벌 hook 설정)
"""
import json
import shutil
from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
SCRIPTS_DIR = CLAUDE_DIR / "scripts"

# 이 스크립트가 포함된 프로젝트의 글로벌 스크립트 소스
SOURCE_DIR = Path(__file__).parent.parent


def install_scripts():
    """스크립트 파일 복사"""
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

    # obsidian_auto_log.py (이미 글로벌 경로에 있으면 업데이트, 없으면 복사)
    src_auto_log = SOURCE_DIR / "scripts" / "install_global_hooks.py"
    # 소스는 이 프로젝트가 아니라 직접 작성
    auto_log_content = (SCRIPTS_DIR / "obsidian_auto_log.py")
    init_vault_content = (SCRIPTS_DIR / "init_vault.py")

    if auto_log_content.exists():
        print(f"[OK] obsidian_auto_log.py 이미 존재: {auto_log_content}")
    else:
        print(f"[!] obsidian_auto_log.py 없음 - 생성합니다")
        _write_auto_log(auto_log_content)

    if init_vault_content.exists():
        print(f"[OK] init_vault.py 이미 존재: {init_vault_content}")
    else:
        print(f"[!] init_vault.py 없음 - 생성합니다")
        _write_init_vault(init_vault_content)


def install_claude_md():
    """글로벌 CLAUDE.md 설치"""
    target = CLAUDE_DIR / "CLAUDE.md"
    if target.exists():
        print(f"[OK] CLAUDE.md 이미 존재: {target}")
        return

    content = '''# 글로벌 Claude Code 지시사항

## Obsidian 자동 기록

프로젝트에 `{프로젝트명}_vault/` 디렉토리가 존재하면 개발 기록을 자동으로 남깁니다.
**vault가 없는 프로젝트에서는 이 규칙을 무시하세요.**

### 언제 기록하는가

- 코드 수정/생성/삭제 후
- 버그 수정 후
- 새 기능 구현 후
- 리팩토링 후
- 설정 변경 후
- 중요한 의사결정을 내린 후

### 기록 방법

**1. 일일 로그 (매 작업 후 필수)**

`{프로젝트명}_vault/01-Daily/YYYY-MM-DD.md` 파일에 append.
파일이 없으면 헤더를 만들고 작성.

**2. 기능/기술/의사결정/대화 기록**

각각 `02-Features/`, `03-Technical/`, `04-Decisions/`, `06-Conversations/`에 작성.

### 주의사항

- 일일 로그는 **append** (절대 덮어쓰지 마세요)
- 시간 형식: `HH:MM` (24시간제), 한국어, 간결하게
- vault가 없는 프로젝트에서는 아무것도 하지 마세요

### Vault 초기화

새 프로젝트에서 vault를 만들려면:
```bash
python ~/.claude/scripts/init_vault.py
```
'''
    target.write_text(content, encoding="utf-8")
    print(f"[OK] CLAUDE.md 생성: {target}")


def install_settings():
    """settings.json에 글로벌 Stop hook 추가"""
    target = CLAUDE_DIR / "settings.json"

    hook_command = 'python -c "from pathlib import Path; exec(Path.home().joinpath(\'.claude/scripts/obsidian_auto_log.py\').read_text())"'

    if target.exists():
        data = json.loads(target.read_text(encoding="utf-8"))
    else:
        data = {}

    # hooks.Stop 이 이미 있는지 확인
    hooks = data.get("hooks", {})
    stop_hooks = hooks.get("Stop", [])

    # 이미 obsidian_auto_log 관련 hook이 있으면 스킵
    already_exists = False
    for entry in stop_hooks:
        for h in entry.get("hooks", []):
            if "obsidian_auto_log" in h.get("command", ""):
                already_exists = True
                break

    if already_exists:
        print(f"[OK] settings.json에 이미 Stop hook 존재")
        return

    # hook 추가
    new_hook = {
        "hooks": [
            {
                "type": "command",
                "command": hook_command,
                "timeout": 15,
                "async": True
            }
        ]
    }
    stop_hooks.append(new_hook)
    hooks["Stop"] = stop_hooks
    data["hooks"] = hooks

    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] settings.json 업데이트: {target}")


def _write_auto_log(path):
    """obsidian_auto_log.py 내용 직접 작성"""
    content = r'''"""
글로벌 Claude Code Stop hook - 개발 변경사항을 Obsidian daily note에 자동 기록
"""
import sys
import json
import subprocess
from pathlib import Path
from datetime import datetime

IGNORE_PATTERNS = ["_vault/", ".claude/", ".git/", "__pycache__/", ".pyc", "CLAUDE.md"]
TRIVIAL_LINES = {"", "pass", "}", "]", ")", "else:", "return", "break", "continue"}


def get_project_root():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def get_unstaged_changes(project_root):
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=10
        )
        files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        result2 = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, encoding="utf-8",
            cwd=str(project_root), timeout=10
        )
        staged = [f.strip() for f in result2.stdout.strip().split("\n") if f.strip()]
        all_files = list(set(files + staged))
        return [f for f in all_files if not any(pat in f for pat in IGNORE_PATTERNS)]
    except Exception:
        return []


def _parse_diff(diff_text, stats, previews):
    current_file = None
    added_count = 0
    deleted_count = 0
    added_lines = []
    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            if current_file and current_file not in stats:
                stats[current_file] = (added_count, deleted_count)
                if added_lines:
                    previews[current_file] = added_lines[:3]
            parts = line.split(" b/")
            current_file = parts[1] if len(parts) == 2 else None
            added_count = 0
            deleted_count = 0
            added_lines = []
        elif line.startswith("+") and not line.startswith("+++"):
            added_count += 1
            stripped = line[1:].strip()
            if stripped not in TRIVIAL_LINES and len(stripped) > 3:
                if len(stripped) > 80:
                    stripped = stripped[:77] + "..."
                added_lines.append(stripped)
        elif line.startswith("-") and not line.startswith("---"):
            deleted_count += 1
    if current_file and current_file not in stats:
        stats[current_file] = (added_count, deleted_count)
        if added_lines:
            previews[current_file] = added_lines[:3]


def get_diff_details(project_root):
    stats = {}
    previews = {}
    for cached_flag in [[], ["--cached"]]:
        try:
            result = subprocess.run(
                ["git", "diff"] + cached_flag,
                capture_output=True, text=True, encoding="utf-8",
                cwd=str(project_root), timeout=8
            )
            if result.stdout.strip():
                _parse_diff(result.stdout, stats, previews)
        except Exception:
            pass
    return stats, previews


def get_daily_note_path(vault_path):
    daily_dir = vault_path / "01-Daily"
    daily_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    return daily_dir / f"{today}.md"


def ensure_daily_header(note_path):
    if not note_path.exists():
        now = datetime.now()
        header = f"# {now.strftime('%Y년 %m월 %d일')} 개발 로그\n\n## 오늘의 작업\n\n---\n"
        note_path.write_text(header, encoding="utf-8")


def already_logged_recently(note_path, files):
    if not note_path.exists():
        return False
    try:
        content = note_path.read_text(encoding="utf-8")
        recent = content[-800:]
        for f in files:
            if f not in recent:
                return False
        return True
    except Exception:
        return False


def log_changes(vault_path, project_root, files):
    if not files:
        return
    note_path = get_daily_note_path(vault_path)
    ensure_daily_header(note_path)
    if already_logged_recently(note_path, files):
        return
    now = datetime.now().strftime("%H:%M")
    stats, previews = get_diff_details(project_root)
    total_added = 0
    total_deleted = 0
    file_lines = []
    for f in files[:10]:
        if f in stats:
            added, deleted = stats[f]
            total_added += added
            total_deleted += deleted
            file_lines.append(f"  - `{f}` (+{added}/-{deleted})")
        else:
            file_lines.append(f"  - `{f}`")
    if len(files) > 10:
        file_lines.append(f"  - ... 외 {len(files) - 10}개")
    files_list = "\n".join(file_lines)
    project_name = project_root.name
    entry = f"\n### {now} - [Auto] 코드 변경 감지 ({project_name})\n\n"
    entry += f"**변경 파일:** ({len(files)}개, +{total_added} / -{total_deleted})\n"
    entry += f"{files_list}\n"
    preview_lines = []
    for f in files[:5]:
        if f in previews:
            for pline in previews[f][:2]:
                preview_lines.append(f"  - `{pline}`")
    if preview_lines:
        entry += f"\n**주요 추가 내용:**\n"
        entry += "\n".join(preview_lines[:8])
        entry += "\n"
    entry += "\n---\n"
    with open(note_path, "a", encoding="utf-8") as f:
        f.write(entry)


def main():
    try:
        stdin_data = sys.stdin.read()
        if stdin_data:
            data = json.loads(stdin_data)
        else:
            data = {}
    except Exception:
        data = {}
    project_root = get_project_root()
    if not project_root:
        return
    vault_path = project_root / f"{project_root.name}_vault"
    if not vault_path.is_dir():
        return
    changed_files = get_unstaged_changes(project_root)
    if changed_files:
        log_changes(vault_path, project_root, changed_files)


if __name__ == "__main__":
    main()
'''
    path.write_text(content.lstrip(), encoding="utf-8")


def _write_init_vault(path):
    """init_vault.py 내용 직접 작성"""
    content = r'''"""
Obsidian vault 초기화 스크립트

사용법:
    cd ~/Desktop/new-project
    python ~/.claude/scripts/init_vault.py
"""
import subprocess
from pathlib import Path
from datetime import datetime


def get_project_root():
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except Exception:
        pass
    return Path.cwd()


def create_vault(project_root):
    project_name = project_root.name
    vault = project_root / f"{project_name}_vault"
    if vault.exists():
        print(f"[!] {vault.name}/ 이미 존재합니다: {vault}")
        return False
    dirs = ["00-Index", "01-Daily", "02-Features", "03-Technical", "04-Decisions", "06-Conversations"]
    for d in dirs:
        (vault / d).mkdir(parents=True, exist_ok=True)
    dashboard = f"""# {project_name} Dashboard\n\n#index #dashboard\n\n## 프로젝트 현황\n\n| 항목 | 상태 |\n|------|------|\n| 프로젝트명 | {project_name} |\n| 생성일 | {datetime.now().strftime('%Y-%m-%d')} |\n"""
    (vault / "00-Index" / "Dashboard.md").write_text(dashboard, encoding="utf-8")
    index = f"""# {project_name} Index\n\n#index\n\n## 디렉토리 구조\n\n- **00-Index/** - 대시보드, 색인\n- **01-Daily/** - 일일 개발 로그\n- **02-Features/** - 기능별 문서\n- **03-Technical/** - 기술 문서\n- **04-Decisions/** - 의사결정 기록\n- **06-Conversations/** - Claude 대화 기록\n"""
    (vault / "00-Index" / "Index.md").write_text(index, encoding="utf-8")
    conv_readme = """# Claude 대화 기록\n\n#conversation #index\n\n이 폴더에는 Claude Code와의 주요 대화 내용이 기록됩니다.\n\n## 대화 목록\n\n| 날짜 | 주제 | 태그 |\n|------|------|------|\n| - | - | - |\n"""
    (vault / "06-Conversations" / "README.md").write_text(conv_readme, encoding="utf-8")
    today = datetime.now()
    daily_path = vault / "01-Daily" / f"{today.strftime('%Y-%m-%d')}.md"
    daily_header = f"# {today.strftime('%Y년 %m월 %d일')} 개발 로그\n\n## 오늘의 작업\n\n---\n"
    daily_path.write_text(daily_header, encoding="utf-8")
    print(f"[OK] {vault.name}/ 생성 완료: {vault}")
    return True


def update_gitignore(project_root):
    gitignore = project_root / ".gitignore"
    project_name = project_root.name
    pattern = f"{project_name}_vault/.obsidian/"
    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8")
        if pattern in content:
            print(f"[OK] .gitignore에 이미 {pattern} 존재")
            return
        if content and not content.endswith("\n"):
            content += "\n"
        content += f"\n# Obsidian 설정 (개인화 파일)\n{pattern}\n"
        gitignore.write_text(content, encoding="utf-8")
    else:
        content = f"# Obsidian 설정 (개인화 파일)\n{pattern}\n"
        gitignore.write_text(content, encoding="utf-8")
    print(f"[OK] .gitignore에 {pattern} 추가")


def main():
    project_root = get_project_root()
    print(f"프로젝트 루트: {project_root}")
    print(f"프로젝트명: {project_root.name}")
    print()
    created = create_vault(project_root)
    if created:
        update_gitignore(project_root)
        print()
        print("=== 초기화 완료 ===")
        print("이제 Claude Code 사용 시 자동으로 개발 기록이 남습니다.")
    else:
        print()
        print("기존 vault를 유지합니다.")


if __name__ == "__main__":
    main()
'''
    path.write_text(content.lstrip(), encoding="utf-8")


def main():
    print("=== 글로벌 Obsidian 자동 로깅 설치 ===")
    print(f"설치 경로: {CLAUDE_DIR}")
    print()

    install_scripts()
    install_claude_md()
    install_settings()

    print()
    print("=== 설치 완료! ===")
    print("이제 Claude Code에서 자동 기록이 동작합니다.")
    print()
    print("새 프로젝트에서 vault 만들기:")
    print("  python ~/.claude/scripts/init_vault.py")


if __name__ == "__main__":
    main()
