# Git Hook 자동 설치 스크립트
# post-commit hook을 자동으로 설치

import os
import stat
from pathlib import Path
import shutil


def setup_git_hooks():
    """Git hooks 설정"""
    project_root = Path(__file__).parent.parent
    git_hooks_dir = project_root / ".git" / "hooks"

    # .git 폴더 확인
    if not git_hooks_dir.exists():
        print("[ERROR] .git/hooks 폴더가 없습니다.")
        print("   Git 저장소가 아닌가요?")
        print("   'git init'을 먼저 실행하세요.")
        return False

    # post-commit hook 내용
    hook_content = f"""#!/bin/sh
# Git post-commit hook - Obsidian 자동 기록

echo "[LOG] Obsidian 자동 기록 중..."

# Python 스크립트 실행
python "{project_root}/scripts/git_auto_log.py"

# 에러 무시 (기록 실패해도 커밋은 성공)
exit 0
"""

    # Windows용 batch 파일도 생성
    hook_content_bat = f"""@echo off
REM Git post-commit hook - Obsidian 자동 기록

echo [LOG] Obsidian 자동 기록 중...

REM Python 스크립트 실행
python "{project_root}\\scripts\\git_auto_log.py"

REM 에러 무시
exit /b 0
"""

    # post-commit 파일 경로
    hook_file = git_hooks_dir / "post-commit"
    hook_file_bat = git_hooks_dir / "post-commit.bat"

    try:
        # 기존 파일 백업
        if hook_file.exists():
            backup_file = git_hooks_dir / "post-commit.backup"
            shutil.copy(hook_file, backup_file)
            print(f"[OK] 기존 hook 백업: {backup_file}")

        # post-commit 파일 작성 (Unix/Git Bash용)
        with open(hook_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(hook_content)

        # 실행 권한 부여 (Unix 시스템)
        try:
            current_permissions = hook_file.stat().st_mode
            hook_file.chmod(current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            print(f"[OK] 실행 권한 설정: {hook_file}")
        except Exception as e:
            print(f"[WARN] 실행 권한 설정 실패 (Windows에서는 정상): {e}")

        # Windows batch 파일 작성
        with open(hook_file_bat, "w", encoding="utf-8") as f:
            f.write(hook_content_bat)

        print(f"[OK] Git hook 설치 완료!")
        print(f"   위치: {hook_file}")
        print(f"   (Windows): {hook_file_bat}")
        print()
        print("이제 'git commit' 할 때마다 자동으로 Obsidian에 기록됩니다!")

        return True

    except Exception as e:
        print(f"[ERROR] Git hook 설치 실패: {e}")
        return False


def test_git_hook():
    """Git hook 테스트"""
    print()
    print("[TEST] Git hook 테스트...")
    print("다음 명령어로 테스트해보세요:")
    print()
    print("  1. 파일 수정: echo 'test' >> test.txt")
    print("  2. Git 추가: git add test.txt")
    print("  3. Git 커밋: git commit -m 'Test auto-logging'")
    print("  4. Obsidian 확인: 01-Daily/[오늘 날짜].md")
    print()


def uninstall_git_hooks():
    """Git hooks 제거"""
    project_root = Path(__file__).parent.parent
    git_hooks_dir = project_root / ".git" / "hooks"

    hook_file = git_hooks_dir / "post-commit"
    hook_file_bat = git_hooks_dir / "post-commit.bat"
    backup_file = git_hooks_dir / "post-commit.backup"

    removed = []

    if hook_file.exists():
        hook_file.unlink()
        removed.append(str(hook_file))

    if hook_file_bat.exists():
        hook_file_bat.unlink()
        removed.append(str(hook_file_bat))

    if removed:
        print(f"[OK] Git hook 제거 완료:")
        for f in removed:
            print(f"   - {f}")

        # 백업 복원
        if backup_file.exists():
            shutil.copy(backup_file, hook_file)
            print(f"[OK] 백업 복원: {backup_file} -> {hook_file}")
    else:
        print("[INFO] 제거할 Git hook이 없습니다.")


def main():
    """메인 함수"""
    import sys

    print("=" * 60)
    print("Git Hook 자동 설치")
    print("=" * 60)
    print()

    if len(sys.argv) > 1 and sys.argv[1] == "uninstall":
        uninstall_git_hooks()
    else:
        success = setup_git_hooks()
        if success:
            test_git_hook()


if __name__ == "__main__":
    main()
