# -*- coding: utf-8 -*-
"""
docs + obsidian_vault → G:\\내 드라이브\\Obsidian\\10. project\\Coupong 으로 병합·이동
실행 후 프로젝트에서 docs/, obsidian_vault/ 삭제
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
VAULT = ROOT / "obsidian_vault"
COUPONG = VAULT / "10. project" / "Coupong"
GDRIVE = Path(r"G:\내 드라이브\Obsidian\10. project\Coupong")


def merge_docs_into_coupong():
    """docs/ → Coupong/03-Technical"""
    if not DOCS.exists():
        return
    dest_dir = COUPONG / "03-Technical"
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in DOCS.iterdir():
        if f.is_file():
            shutil.copy2(f, dest_dir / f.name)
            print(f"  docs -> 03-Technical: {f.name}")


def merge_root_vault_into_coupong():
    """obsidian_vault 루트 01-Daily, 06-Conversations → Coupong (없는 파일만)"""
    for sub in ["01-Daily", "06-Conversations"]:
        src_dir = VAULT / sub
        dest_dir = COUPONG / sub
        if not src_dir.exists():
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for f in src_dir.iterdir():
            if f.is_file():
                dest_file = dest_dir / f.name
                if not dest_file.exists() or f.stat().st_mtime > dest_file.stat().st_mtime:
                    shutil.copy2(f, dest_file)
                    print(f"  vault/{sub} -> Coupong: {f.name}")


def copy_to_gdrive():
    """병합된 Coupong → G:"""
    GDRIVE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(COUPONG, GDRIVE, dirs_exist_ok=True)
    print(f"[OK] G: 복사 완료: {GDRIVE}")


def main():
    print("[1] docs -> Coupong/03-Technical")
    merge_docs_into_coupong()
    print("[2] vault 루트 01-Daily, 06-Conversations -> Coupong")
    merge_root_vault_into_coupong()
    print("[3] Coupong -> G:")
    copy_to_gdrive()
    print("\n다음: 프로젝트에서 docs/, obsidian_vault/ 삭제 후 참조 업데이트")


if __name__ == "__main__":
    main()
