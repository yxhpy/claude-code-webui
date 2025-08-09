import os
from pathlib import Path
from typing import List


def ccui_content() -> str:
    return (
        "@echo off\n"
        "set ENV_FILE=%USERPROFILE%\\.claude-code-env.bat\n"
        "if exist \"%ENV_FILE%\" (\n"
        "  call \"%ENV_FILE%\"\n"
        ")\n"
        "claude %*\n"
    )


def candidate_dirs() -> List[Path]:
    user_env = Path(os.environ.get("USERPROFILE", str(Path.home())))
    home_user = Path.home()
    bases = []
    for b in {user_env, home_user}:
        bases.append(b)
        # 生成另一块盘的候选（C: <-> D:）
        try:
            drive = b.drive.upper() or "C:"
            other = "D:" if drive == "C:" else ("C:" if drive == "D:" else "")
            if other:
                bases.append(Path(other + b.as_posix()[2:]))
        except Exception:
            pass
    # 去重并展开子目录
    seen = set()
    dirs: List[Path] = []
    for base in bases:
        for sub in [
            base / "AppData" / "Local" / "bin",
            base / "AppData" / "Roaming" / "npm",
        ]:
            key = str(sub).lower()
            if key not in seen:
                seen.add(key)
                dirs.append(sub)
    return dirs


def write_once(dir_path: Path) -> tuple[Path, bool, str]:
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
        dest = dir_path / "ccui.bat"
        dest.write_text(ccui_content(), encoding="utf-8")
        return dest, dest.exists(), ""
    except Exception as e:
        return dir_path / "ccui.bat", False, str(e)


def main() -> None:
    print("USERPROFILE:", os.environ.get("USERPROFILE", ""))
    print("Path.home():", str(Path.home()))
    tried = []
    for d in candidate_dirs():
        dest, ok, err = write_once(d)
        tried.append((str(dest), ok, err))
        print("try:", dest, "ok:" , ok, ("err:" + err) if err else "")
    # 汇总首个成功位置
    first_ok = next((t[0] for t in tried if t[1]), "")
    print("primary_success:", first_ok)


if __name__ == "__main__":
    main() 