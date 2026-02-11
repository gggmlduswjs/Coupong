# -*- coding: utf-8 -*-
"""Google Drive Obsidian 폴더로 Coupong vault 복사 (sync_obsidian.py to 호출)"""
import subprocess
import sys
from pathlib import Path

if __name__ == "__main__":
    script = Path(__file__).parent / "sync_obsidian.py"
    sys.exit(subprocess.call([sys.executable, str(script), "to"]))
