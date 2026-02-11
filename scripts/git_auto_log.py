# Git 커밋 자동 기록
# Git hook에서 호출되어 커밋 내용을 Obsidian에 자동 기록

import sys
import io
import subprocess
from datetime import datetime
from pathlib import Path

# Windows cp949 콘솔에서 유니코드 출력 에러 방지
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 프로젝트 루트 경로 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from obsidian_logger import ObsidianLogger


def get_last_commit_info():
    """마지막 커밋 정보 가져오기"""
    try:
        # 커밋 메시지
        commit_msg = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            cwd=project_root,
            encoding="utf-8"
        ).strip()

        # 커밋 해시
        commit_hash = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%h"],
            cwd=project_root,
            encoding="utf-8"
        ).strip()

        # 변경된 파일 목록
        changed_files = subprocess.check_output(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
            cwd=project_root,
            encoding="utf-8"
        ).strip().split("\n")

        # 통계
        stats = subprocess.check_output(
            ["git", "diff-tree", "--no-commit-id", "--numstat", "-r", "HEAD"],
            cwd=project_root,
            encoding="utf-8"
        ).strip().split("\n")

        total_added = 0
        total_deleted = 0
        for stat in stats:
            if stat:
                parts = stat.split("\t")
                if len(parts) >= 2 and parts[0] != "-" and parts[1] != "-":
                    total_added += int(parts[0])
                    total_deleted += int(parts[1])

        return {
            "message": commit_msg,
            "hash": commit_hash,
            "files": changed_files,
            "added": total_added,
            "deleted": total_deleted
        }

    except subprocess.CalledProcessError as e:
        print(f"Git 명령 실행 실패: {e}")
        return None


def log_commit_to_obsidian(commit_info):
    """커밋 정보를 Obsidian에 기록"""
    if not commit_info:
        return

    logger = ObsidianLogger()

    # 커밋 메시지 분석
    message = commit_info["message"]
    first_line = message.split("\n")[0]

    # 파일 목록 포맷
    files_list = "\n".join(f"  - `{f}`" for f in commit_info["files"][:10])
    if len(commit_info["files"]) > 10:
        files_list += f"\n  - ... 외 {len(commit_info['files']) - 10}개"

    # 통계
    stats_text = f"+{commit_info['added']} -{commit_info['deleted']}"

    # Obsidian 내용 생성
    content = f"""
## [GIT] Commit: {first_line}

**커밋 해시:** `{commit_info['hash']}`

**커밋 메시지:**
```
{message}
```

**변경 통계:** {stats_text} 줄

**변경 파일:** ({len(commit_info['files'])}개)
{files_list}

**시간:** {datetime.now().strftime('%H:%M:%S')}
"""

    # 일일 노트에 기록
    logger.log_to_daily(content, f"Git: {first_line}")

    print(f"[OK] Obsidian에 커밋 기록 완료: {first_line}")


def main():
    """메인 함수"""
    print("[LOG] Git 커밋 자동 기록 시작...")

    # 커밋 정보 가져오기
    commit_info = get_last_commit_info()

    if commit_info:
        # Obsidian에 기록
        log_commit_to_obsidian(commit_info)
        print("[OK] 완료!")
    else:
        print("[ERROR] 커밋 정보를 가져올 수 없습니다.")
        sys.exit(1)


if __name__ == "__main__":
    main()
