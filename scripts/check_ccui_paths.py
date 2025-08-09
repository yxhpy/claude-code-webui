import os
from pathlib import Path

CANDIDATES = []
user = os.environ.get("USERNAME", "Administrator")
for drive in ("C:", "D:"):
    base = Path(drive + "\\") / "Users" / user / "AppData" / "Local" / "bin"
    CANDIDATES.append(base / "ccui.bat")

for p in CANDIDATES:
    try:
        exists = p.exists()
        print("path:", str(p))
        print("exists:", exists)
        if exists:
            fi = p.stat()
            print("size:", fi.st_size)
            print("mtime:", fi.st_mtime)
    except Exception as e:
        print("path:", str(p))
        print("error:", str(e)) 