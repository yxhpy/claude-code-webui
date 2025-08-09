import os
import sys
from pathlib import Path
from ctypes import POINTER, byref, windll, wintypes

# FOLDERID_LocalAppData = {F1B32785-6FBA-4FCF-9D55-7B8E7F157091}
FOLDERID_LocalAppData = wintypes.GUID('{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}')
SHGetKnownFolderPath = windll.shell32.SHGetKnownFolderPath
CoTaskMemFree = windll.ole32.CoTaskMemFree

SHGetKnownFolderPath.argtypes = [POINTER(wintypes.GUID), wintypes.DWORD, wintypes.HANDLE, POINTER(wintypes.LPWSTR)]
SHGetKnownFolderPath.restype = wintypes.HRESULT


def get_localappdata() -> Path:
    ppszPath = wintypes.LPWSTR()
    hr = SHGetKnownFolderPath(byref(FOLDERID_LocalAppData), 0, None, byref(ppszPath))
    if hr != 0:
        raise OSError(f'SHGetKnownFolderPath failed: HRESULT=0x{hr:08X}')
    try:
        return Path(ppszPath.value)
    finally:
        CoTaskMemFree(ppszPath)


def ccui_content() -> str:
    return (
        "@echo off\n"
        "set ENV_FILE=%USERPROFILE%\\.claude-code-env.bat\n"
        "if exist \"%ENV_FILE%\" (\n"
        "  call \"%ENV_FILE%\"\n"
        ")\n"
        "claude %*\n"
    )


def main() -> None:
    try:
        local = get_localappdata()
    except Exception as e:
        print('get_localappdata_error:', str(e))
        # 回退到环境变量
        local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local')))
    target_dir = local / 'bin'
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / 'ccui.bat'
    dest.write_text(ccui_content(), encoding='utf-8')
    print('localappdata:', str(local))
    print('ccui_written:', str(dest))
    print('exists:', dest.exists())


if __name__ == '__main__':
    if sys.platform != 'win32':
        print('This script is for Windows only.')
        sys.exit(1)
    main() 