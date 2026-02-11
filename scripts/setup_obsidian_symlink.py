# -*- coding: utf-8 -*-
"""
obsidian_vault/10. project/Coupong → G: 심볼릭 링크 생성

실행 후 모든 기록(일일 로그, 기술 문서 등)이 Google Drive에 직접 저장됩니다.
sync from/to 불필요.

사용법: python scripts/setup_obsidian_symlink.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
LINK_PATH = ROOT / "obsidian_vault" / "10. project" / "Coupong"


def load_env():
    env = {}
    env_path = ROOT / ".env"
    if env_path.exists():
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    env = load_env()
    gdrive_base = env.get("OBSIDIAN_VAULT_PATH")
    if not gdrive_base:
        print("[ERROR] .env에 OBSIDIAN_VAULT_PATH를 설정하세요.")
        sys.exit(1)
    target = Path(gdrive_base) / "10. project" / "Coupong"

    if not target.exists():
        print(f"[ERROR] 대상 폴더 없음: {target}")
        print("  Google Drive Obsidian 폴더가 있는지 확인하세요.")
        sys.exit(1)

    if LINK_PATH.exists():
        if LINK_PATH.is_symlink():
            if LINK_PATH.resolve() == target.resolve():
                print("[OK] 심볼릭 링크 이미 설정됨")
                return 0
            LINK_PATH.unlink()
        else:
            print(f"[!] {LINK_PATH} 이(가) 이미 존재합니다. symlink로 교체하려면 수동 삭제 후 재실행하세요.")
            sys.exit(1)

    LINK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LINK_PATH.symlink_to(target, target_is_directory=True)
    print(f"[OK] 심볼릭 링크 생성: {LINK_PATH} → {target}")
    print("     이제 모든 Obsidian 기록이 Google Drive에 직접 저장됩니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
