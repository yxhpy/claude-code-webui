import os
import sys
import types

# 确保可以导入项目根目录下的 app.py
CURRENT_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def test_extract_semver_basic():
    from app import extract_semver

    assert extract_semver("1.2.3") == "1.2.3"
    assert extract_semver("v1.2.3") == "1.2.3"
    assert extract_semver("1.2.3-beta") == "1.2.3"
    assert extract_semver("foo 10.20.30 bar") == "10.20.30"
    assert extract_semver("no version here") == ""


def test_compare_semver():
    from app import compare_semver

    assert compare_semver("1.2.3", "1.2.3") == 0
    assert compare_semver("1.2.3", "1.2.4") == -1
    assert compare_semver("1.3.0", "1.2.10") == 1
    assert compare_semver("2.0.0", "1.10.10") == 1
    assert compare_semver("", "1.0.0") == -1
    assert compare_semver("1.0.0", "") == 1


def test_parse_cli_variants(monkeypatch):
    from app import get_cli_claude_code_version

    # 模拟 'claude -v' 输出
    def fake_run_command(cmd):
        if cmd[:2] == ["claude-code", "--version"]:
            return 127, "", "not found"
        if cmd[:2] == ["claude", "-v"]:
            return 0, "1.0.63 (Claude Code)", ""
        if cmd[:2] == ["claude", "--version"]:
            return 0, "1.0.63 (Claude Code)", ""
        return 127, "", "not found"

    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    from app import run_command_safely as real_run
    import app as app_module
    app_module.run_command_safely = fake_run_command  # type: ignore
    try:
        installed, version = get_cli_claude_code_version()
        assert installed is True
        assert version.startswith("1.0.63")
    finally:
        app_module.run_command_safely = real_run


def test_status_aggregation_vscode(monkeypatch):
    from app import get_claude_code_status, compare_semver
    import app as app_module

    def fake_vscode_version():
        return True, "anthropic.claude-code", "1.0.10"

    def fake_open_vsx_latest(publisher, name):
        # 返回更高版本
        return "1.0.20"

    # 显式模拟 CLI 未安装，避免本机环境存在 `claude -v` 影响用例
    app_module.get_cli_claude_code_version = lambda: (False, "")  # type: ignore
    app_module.get_vscode_claude_code_version = fake_vscode_version  # type: ignore
    app_module.get_open_vsx_latest_version = fake_open_vsx_latest  # type: ignore
    app_module.get_cached_latest_version = lambda: "1.0.15"  # type: ignore
    app_module.get_npm_latest_version = lambda name: "1.0.15"  # type: ignore
    status = get_claude_code_status()
    assert status["installed"] is True
    assert status["source"] == "vscode"
    assert status["current_version"] == "1.0.10"
    # 现逻辑：VSCode 扩展场景也以 npm scoped 包为准
    assert status["latest_version"] == "1.0.15"
    assert status["needs_upgrade"] is True
    assert compare_semver(status["latest_version"], status["current_version"]) == 1


def test_status_aggregation_cli(monkeypatch):
    from app import get_claude_code_status
    import app as app_module

    def fake_vscode_version():
        return False, "", ""

    def fake_cli_version():
        return True, "1.0.30"

    def fake_npm_latest(name):
        # 应优先读取 @anthropic-ai/claude-code
        assert name in ("@anthropic-ai/claude-code",)
        return "1.0.40"

    app_module.get_vscode_claude_code_version = fake_vscode_version  # type: ignore
    app_module.get_cli_claude_code_version = fake_cli_version  # type: ignore
    app_module.get_npm_latest_version = fake_npm_latest  # type: ignore
    app_module.get_open_vsx_latest_version = lambda p, n: "1.0.35"  # type: ignore
    app_module.get_cached_latest_version = lambda: "1.0.40"  # type: ignore

    status = get_claude_code_status()
    assert status["installed"] is True
    assert status["source"] == "cli"
    assert status["current_version"] == "1.0.30"
    assert status["latest_version"] == "1.0.40"
    assert status["needs_upgrade"] is True


