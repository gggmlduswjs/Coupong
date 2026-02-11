# -*- coding: utf-8 -*-
"""
Obsidian vault 동기화 (Google Drive ↔ 프로젝트)

어느 PC에서든 OBSIDIAN_VAULT_PATH만 .env에 설정하면 사용 가능.

사용법:
  python scripts/sync_obsidian.py from   # G: → 프로젝트 (개발 전)
  python scripts/sync_obsidian.py to     # 프로젝트 → G: (개발 후)
"""
import os
import shutil
import sys
from pathlib import Path

# 프로젝트 루트
ROOT = Path(__file__).parent.parent
PROJECT_VAULT = ROOT / "obsidian_vault" / "10. project" / "Coupong"
RELATIVE_IN_GDRIVE = Path("10. project") / "Coupong"


def load_env() -> dict:
    """.env 파일에서 변수 로드"""
    env_path = ROOT / ".env"
    env = {}
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_gdrive_path() -> Path:
    env = load_env()
    path = env.get("OBSIDIAN_VAULT_PATH") or os.environ.get("OBSIDIAN_VAULT_PATH")
    if not path:
        print("[ERROR] .env에 OBSIDIAN_VAULT_PATH를 설정하세요.")
        print("  예: OBSIDIAN_VAULT_PATH=G:\\내 드라이브\\Obsidian")
        print("  Mac: OBSIDIAN_VAULT_PATH=/Users/사용자/Library/CloudStorage/Google Drive/내 드라이브/Obsidian")
        sys.exit(1)
    return Path(path) / RELATIVE_IN_GDRIVE


def sync_from_gdrive():
    """Google Drive → 프로젝트 (개발 전에 실행)"""
    src = get_gdrive_path()
    dest = PROJECT_VAULT
    if not src.exists():
        print(f"[ERROR] 소스 없음: {src}")
        print("  Google Drive 경로와 OBSIDIAN_VAULT_PATH를 확인하세요.")
        sys.exit(1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    print(f"[OK] from: {src} → {dest}")


def sync_to_gdrive():
    """프로젝트 → Google Drive (개발 후에 실행)"""
    src = PROJECT_VAULT
    dest = get_gdrive_path()
    if not src.exists():
        print(f"[ERROR] 소스 없음: {src}")
        sys.exit(1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    print(f"[OK] to: {src} → {dest}")


def main():
    if len(sys.argv) < 2:
        print("사용법:")
        print("  python scripts/sync_obsidian.py from   # G: → 프로젝트 (개발 전)")
        print("  python scripts/sync_obsidian.py to     # 프로젝트 → G: (개발 후)")
        sys.exit(1)
    cmd = sys.argv[1].lower()
    if cmd == "from":
        sync_from_gdrive()
    elif cmd == "to":
        sync_to_gdrive()
    else:
        print(f"[ERROR] 알 수 없는 명령: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
