import platform
from pathlib import Path

from app import (
    install_ccui,
    is_ccui_on_path,
    ensure_windows_bin_on_path,
    ensure_windows_npm_on_path,
)

# _windows_ccui_candidate_dirs 仅在 Windows 下可用
try:
    from app import _windows_ccui_candidate_dirs  # type: ignore
except Exception:
    def _windows_ccui_candidate_dirs():  # type: ignore
        home = Path.home()
        from app import DATA_DIR  # type: ignore
        return [
            home / "AppData" / "Local" / "bin",
            home / "bin",
            home / ".local" / "bin",
            DATA_DIR / "bin",
        ]


def main() -> None:
    print("Platform:", platform.system())
    # 1) 尝试安装 ccui
    path = install_ccui()
    print("ccui path:", path)
    print("exists:", path.exists())

    if platform.system() == "Windows" and not path.exists():
        # 2) 逐个候选目录重试
        for d in _windows_ccui_candidate_dirs():
            try:
                d.mkdir(parents=True, exist_ok=True)
                p = install_ccui(target_dir=d)
                print("retry at:", p, "exists:", p.exists())
                if p.exists():
                    path = p
                    break
            except Exception as e:
                print("retry error at", d, e)

    print("final path:", path, "exists:", path.exists())

    # 3) PATH 修复
    if platform.system() == "Windows":
        s1, m1 = ensure_windows_bin_on_path()
        print("ensure_windows_bin_on_path:", s1, m1)
        s2, m2 = ensure_windows_npm_on_path()
        print("ensure_windows_npm_on_path:", s2, m2)

    # 4) on-path 检测
    on_path, where = is_ccui_on_path()
    print("is_ccui_on_path:", on_path, where)


if __name__ == "__main__":
    main() 