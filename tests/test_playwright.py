import os
import subprocess
import time


def run_server_with_status(env_status: dict, port: int = 5001):
    env = os.environ.copy()
    env["FORCE_CLAUDE_STATUS"] = __import__("json").dumps(env_status)
    env["FLASK_TEST"] = "1"
    env["FLASK_USE_RELOADER"] = "0"
    env["HOST"] = "127.0.0.1"
    env["PORT"] = str(port)
    # 使用项目虚拟环境 Python 启动 app.py
    proc = subprocess.Popen([
        os.path.join(os.getcwd(), ".venv", "bin", "python"),
        "app.py",
    ], env=env)
    time.sleep(1.8)
    return proc, f"http://127.0.0.1:{port}"


def test_ui_install_button_shown(playwright):
    # 未安装时应显示“安装”按钮
    proc, base_url = run_server_with_status({
        "installed": False,
        "source": "",
        "current_version": "",
        "latest_version": "1.0.10",
        "needs_upgrade": False,
        "vscode_ext_id": "",
    }, port=5001)
    try:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(base_url)
        assert page.is_visible("text=安装")
        browser.close()
    finally:
        proc.terminate()


def test_ui_upgrade_button_shown(playwright):
    # 已安装但需要升级时应显示“升级”按钮
    proc, base_url = run_server_with_status({
        "installed": True,
        "source": "vscode",
        "current_version": "1.0.10",
        "latest_version": "1.0.20",
        "needs_upgrade": True,
        "vscode_ext_id": "anthropic.claude-code",
    }, port=5002)
    try:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.goto(base_url)
        assert page.is_visible("text=升级")
        browser.close()
    finally:
        proc.terminate()


