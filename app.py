from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError
import threading
import time
from datetime import datetime

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_sqlalchemy import SQLAlchemy


# 基本路径
BASE_DIR: Path = Path(__file__).resolve().parent
DB_PATH: Path = BASE_DIR / "accounts.db"
# MCP 配置路径：优先项目级、再用户级；可通过 MCP_CONFIG 覆盖
ENV_FILE_PATH: Path = Path(os.environ.get("CLAUDE_ENV_FILE", str(Path.home() / ".claude-code-env")))

# Claude Code 环境变量名
ENV_BASE_URL = "ANTHROPIC_BASE_URL"
ENV_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"


app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
db = SQLAlchemy(app)


class Account(db.Model):
    __tablename__ = "accounts"

    id = db.Column(db.Integer, primary_key=True)
    baseurl = db.Column(db.String(500), nullable=False)
    apikey = db.Column(db.String(500), nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - 简单可读
        return f"<Account id={self.id} baseurl={self.baseurl!r}>"


def ensure_db_initialized() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db.create_all()


def get_mcp_config_path(for_write: bool = False) -> Path:
    override_path = os.environ.get("CLAUDE_MCP_CONFIG")
    if override_path:
        return Path(override_path).expanduser()

    # Claude Code MCP配置优先级：
    # 1. 项目级：.mcp.json (项目根目录)
    # 2. 用户级：~/.claude.json
    project_path = BASE_DIR / ".mcp.json"
    user_claude_json = Path.home() / ".claude.json" 

    if for_write:
        # 写入：优先项目级，其次用户级.claude.json
        return project_path if project_path.exists() else user_claude_json

    # 读取：按优先级查找存在的文件
    for path in [project_path, user_claude_json]:
        if path.exists():
            return path
    
    # 默认返回用户级路径（用于创建新配置）
    return user_claude_json


def read_mcp_json() -> dict:
    # 直接读取 ~/.claude.json 文件中的 mcpServers
    claude_json_path = Path.home() / ".claude.json"
    if not claude_json_path.exists():
        return {}
    try:
        content = claude_json_path.read_text(encoding="utf-8")
        data = json.loads(content) if content.strip() else {}
        return data.get("mcpServers", {})
    except Exception:
        return {}


def write_mcp_json(payload: dict) -> None:
    # 直接更新 ~/.claude.json 文件中的 mcpServers
    claude_json_path = Path.home() / ".claude.json"
    claude_json_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 读取现有配置
    existing_data = {}
    if claude_json_path.exists():
        try:
            existing_data = json.loads(claude_json_path.read_text(encoding="utf-8"))
        except Exception:
            existing_data = {}
    
    # 直接更新 mcpServers
    existing_data["mcpServers"] = payload
    
    # 写回文件
    claude_json_path.write_text(json.dumps(existing_data, ensure_ascii=False, indent=2), encoding="utf-8")


def set_default_account_to_mcp(account: Account) -> None:
    # 兼容保留：不再作为主路径使用
    data = read_mcp_json()
    data.update({"baseurl": account.baseurl, "apikey": account.apikey})
    write_mcp_json(data)


def write_env_file(baseurl: str, apikey: str) -> None:
    content = (
        f"export {ENV_BASE_URL}={baseurl}\n"
        f"export {ENV_AUTH_TOKEN}={apikey}\n"
    )
    ENV_FILE_PATH.write_text(content, encoding="utf-8")


def launchctl_setenv(var: str, value: str) -> tuple[int, str, str]:
    return run_command_safely(["launchctl", "setenv", var, value])


def launchctl_getenv(var: str) -> str:
    code, out, _ = run_command_safely(["launchctl", "getenv", var])
    return out if code == 0 else ""


def apply_env_settings(baseurl: str, apikey: str) -> None:
    # 写 shell 环境文件，便于用户 source 使用
    write_env_file(baseurl, apikey)
    # 尝试设置到 launchctl 用户环境，便于新启动的 GUI/终端应用继承
    launchctl_setenv(ENV_BASE_URL, baseurl)
    launchctl_setenv(ENV_AUTH_TOKEN, apikey)


# ---- ccui 工具安装与检测 ----
def generate_ccui_script() -> str:
    script = f"""#!/bin/zsh
set -euo pipefail
ENV_FILE="${{CLAUDE_ENV_FILE:-{ENV_FILE_PATH}}}"
if [ -f "$ENV_FILE" ]; then
  . "$ENV_FILE"
fi
exec claude "$@"
"""
    return script


def install_ccui(target_dir: Path | None = None) -> Path:
    if target_dir is None:
        # 优先 ~/.local/bin，其次 ~/bin
        candidate = Path.home() / ".local" / "bin"
        if not candidate.exists():
            candidate = Path.home() / "bin"
        candidate.mkdir(parents=True, exist_ok=True)
        target_dir = candidate
    target_path = target_dir / "ccui"
    target_path.write_text(generate_ccui_script(), encoding="utf-8")
    target_path.chmod(0o755)
    return target_path


def is_ccui_on_path() -> tuple[bool, str]:
    code, out, _ = run_command_safely(["which", "ccui"])  # noqa: S603
    return (code == 0 and bool(out)), out


def ensure_cli_and_ccui_installed() -> None:
    # 1) 确保 claude CLI 可用
    if not command_exists("claude"):
        if command_exists("npm"):
            run_command_safely(["npm", "-g", "install", "@anthropic-ai/claude-code"])  # noqa: S603
        # 若无 npm 则无法自动安装，UI 上仍可提示

    # 2) 安装 ccui 脚本
    installed, _ = is_ccui_on_path()
    if not installed:
        install_ccui()


def ensure_local_bin_on_path() -> tuple[bool, str]:
    """确保 ~/.local/bin 写入 PATH（zsh 的 .zprofile 与 .zshrc），并更新 launchctl PATH。

    返回 (已处理?, 追加到的文件列表字符串)
    """
    local_bin_dir = Path.home() / ".local" / "bin"
    local_bin_dir.mkdir(parents=True, exist_ok=True)

    appended_files: list[str] = []
    current_path_env = os.environ.get("PATH", "")

    def append_if_missing(target_file: Path) -> None:
        try:
            content = target_file.read_text(encoding="utf-8") if target_file.exists() else ""
            if str(local_bin_dir) not in content:
                with target_file.open("a", encoding="utf-8") as w:
                    w.write("\n# Added by ccui setup: ensure local bin is on PATH\n")
                    w.write(f'export PATH="{local_bin_dir}:{current_path_env}"\n')
                appended_files.append(str(target_file))
        except Exception:
            # 忽略写入失败
            pass

    # 常见 zsh 配置文件
    append_if_missing(Path.home() / ".zprofile")
    append_if_missing(Path.home() / ".zshrc")

    # 更新 launchctl PATH，便于新 GUI/终端继承
    code, out, _ = run_command_safely(["launchctl", "getenv", "PATH"])  # noqa: S603
    launchctl_path = out if code == 0 and out else current_path_env
    if launchctl_path:
        parts = launchctl_path.split(":")
        if str(local_bin_dir) not in parts:
            new_path = f"{local_bin_dir}:{launchctl_path}"
            run_command_safely(["launchctl", "setenv", "PATH", new_path])  # noqa: S603

    return True, ", ".join(appended_files)


def mask_key(key: str, keep: int = 4) -> str:
    if not key:
        return ""
    if len(key) <= keep:
        return "*" * len(key)
    return f"{'*' * (len(key) - keep)}{key[-keep:]}"


def run_command_safely(cmd: list[str]) -> tuple[int, str, str]:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except FileNotFoundError as e:
        return 127, "", str(e)


def get_claude_version() -> tuple[bool, str]:
    """返回 (已安装?, 当前版本字符串)。

    为了稳定比较，优先以 pip 安装版本为准；若无则尝试 CLI 输出。
    """
    # 先用 pip show 获取精确版本
    code, out, _ = run_command_safely([sys.executable, "-m", "pip", "show", "claude"])  # noqa: S603
    if code == 0 and out:
        version_line = next((line for line in out.splitlines() if line.lower().startswith("version:")), "")
        version = version_line.split(":", 1)[1].strip() if ":" in version_line else ""
        if version:
            return True, version

    # 回退到 CLI 版本（可能不是纯版本号，仅做展示用途）
    code, out, _ = run_command_safely(["claude", "--version"])
    if code == 0 and out:
        return True, out

    return False, "not installed"


def get_npm_latest_version(package_name: str) -> str:
    """查询 NPM 最新版本（失败返回空字符串）。"""
    url = f"https://registry.npmjs.org/{package_name}"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=6) as resp:  # nosec - 仅访问 NPM 元数据
            data = json.loads(resp.read().decode("utf-8"))
            dist_tags = data.get("dist-tags", {})
            latest = dist_tags.get("latest", "")
            return latest
    except (URLError, TimeoutError, ValueError, KeyError):
        return ""


# 简单的内存缓存与后台刷新
LATEST_VERSION_CACHE_LOCK = threading.Lock()
LATEST_VERSION_CACHE: dict[str, str | float] = {"value": "", "updated_ts": 0.0}


def get_cached_latest_version() -> str:
    with LATEST_VERSION_CACHE_LOCK:
        value = str(LATEST_VERSION_CACHE.get("value") or "")
    # 允许通过环境变量强制覆盖（便于测试/演示）
    forced = os.environ.get("FORCE_LATEST_VERSION", "").strip()
    return forced or value


def set_cached_latest_version(value: str) -> None:
    with LATEST_VERSION_CACHE_LOCK:
        LATEST_VERSION_CACHE["value"] = value
        LATEST_VERSION_CACHE["updated_ts"] = time.time()


def background_latest_version_refresher(interval_seconds: int = 600) -> None:
    while True:
        try:
            latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
            if latest:
                set_cached_latest_version(latest)
        except Exception:
            # 忽略后台刷新异常，下一轮再试
            pass
        time.sleep(interval_seconds)


def get_open_vsx_latest_version(publisher: str, name: str) -> str:
    """查询 Open VSX 最新版本（失败返回空字符串）。"""
    url = f"https://open-vsx.org/api/{publisher}/{name}/latest"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=6) as resp:  # nosec - 仅访问 Open VSX 元数据
            data = json.loads(resp.read().decode("utf-8"))
            version = data.get("version", "") if isinstance(data, dict) else ""
            return version
    except (URLError, TimeoutError, ValueError, KeyError):
        return ""


def command_exists(command: str) -> bool:
    code, _, _ = run_command_safely([command, "--version"])
    return code == 0


def extract_semver(text: str) -> str:
    """从文本中提取首个 x.y.z 形式的语义化版本号。失败返回空字符串。"""
    import re

    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return match.group(0) if match else ""


def compare_semver(a: str, b: str) -> int:
    """比较两个语义化版本号。

    返回值：-1 (a<b), 0 (a==b), 1 (a>b)。空字符串视为最小。
    """
    if not a and not b:
        return 0
    if not a:
        return -1
    if not b:
        return 1
    try:
        pa = [int(x) for x in a.split(".")]
        pb = [int(x) for x in b.split(".")]
        for xa, xb in zip(pa, pb):
            if xa < xb:
                return -1
            if xa > xb:
                return 1
        if len(pa) < len(pb):
            return -1
        if len(pa) > len(pb):
            return 1
        return 0
    except Exception:
        # 不可解析则退化为字符串比较
        return (a > b) - (a < b)


def get_vscode_claude_code_version() -> tuple[bool, str, str]:
    """检测 VSCode 扩展是否安装，并返回 (已安装?, 扩展ID, 版本)。

    优先 anthropic.claude-code，次选 anthropic.claude。
    """
    code, out, _ = run_command_safely(["code", "--list-extensions", "--show-versions"])  # noqa: S603
    if code != 0 or not out:
        return False, "", ""

    target_ids = ["anthropic.claude-code", "anthropic.claude"]
    found_id = ""
    found_version = ""
    for line in out.splitlines():
        line = line.strip()
        for ext_id in target_ids:
            if line.startswith(ext_id + "@"):  # 例如 anthropic.claude-code@1.2.3
                found_id = ext_id
                found_version = line.split("@", 1)[1]
                break
        if found_id:
            break

    return (bool(found_id), found_id, found_version)


def get_cli_claude_code_version() -> tuple[bool, str]:
    """检测 CLI 是否存在，并返回 (已安装?, 版本)。

    优先顺序：claude-code --version -> claude -v -> claude --version
    """
    code, out, _ = run_command_safely(["claude-code", "--version"])  # noqa: S603
    if code == 0 and out:
        ver = extract_semver(out) or out.strip()
        return True, ver

    code, out, _ = run_command_safely(["claude", "-v"])  # noqa: S603
    if code == 0 and out:
        ver = extract_semver(out) or out.strip()
        return True, ver

    code, out, _ = run_command_safely(["claude", "--version"])  # noqa: S603
    if code == 0 and out:
        ver = extract_semver(out) or out.strip()
        return True, ver

    return False, ""


def get_claude_code_status() -> dict:
    """返回 Claude Code 安装状态与版本信息。

    优先 VSCode 扩展；若无，则回退到 CLI。
    数据结构：
    {
      'installed': bool,
      'source': 'vscode' | 'cli' | '',
      'current_version': str,
      'latest_version': str,
      'needs_upgrade': bool,
      'vscode_ext_id': str
    }
    """
    # 1) CLI（优先使用 claude -v / claude-code --version 作为“当前版本”）
    cli_installed, cli_version = get_cli_claude_code_version()
    if cli_installed:
        # 以缓存的 npm scoped 包版本作为“最新”
        latest = get_cached_latest_version() or ""
        if not latest:
            latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
        needs = bool(latest and cli_version and compare_semver(cli_version, latest) < 0)
        return {
            "installed": True,
            "source": "cli",
            "current_version": cli_version,
            "latest_version": latest,
            "needs_upgrade": needs,
            "vscode_ext_id": "",
        }

    # 2) VSCode 扩展（回退）
    installed, ext_id, current = get_vscode_claude_code_version()
    if installed:
        # 使用缓存的 npm scoped 包作为“最新”展示
        latest = get_cached_latest_version() or ""
        if not latest:
            latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
        needs = bool(latest and current and compare_semver(current, latest) < 0)
        return {
            "installed": True,
            "source": "vscode",
            "current_version": current,
            "latest_version": latest,
            "needs_upgrade": needs,
            "vscode_ext_id": ext_id or "",
        }

    # 3) 未安装
    # 未安装时，也以缓存中的 npm scoped 包为“最新”展示
    fallback_latest = get_cached_latest_version() or ""
    if not fallback_latest:
        fallback_latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
    return {
        "installed": False,
        "source": "",
        "current_version": "",
        "latest_version": fallback_latest,
        "needs_upgrade": False,
        "vscode_ext_id": "",
    }


@app.route("/")
def index():
    accounts = Account.query.order_by(Account.id.desc()).all()
    mcp = read_mcp_json()  # 当前 Claude Code 路由/MCP 配置内容
    # 调试：输出实际使用的配置文件路径
    actual_path = get_mcp_config_path(for_write=False)
    print(f"DEBUG: 实际读取的MCP配置文件路径: {actual_path}")
    
    # 如果找不到标准配置文件，尝试检查Cursor配置
    cursor_mcp_path = Path.home() / ".cursor" / "mcp.json"
    if not actual_path.exists() and cursor_mcp_path.exists():
        print(f"DEBUG: 检测到Cursor MCP配置: {cursor_mcp_path}")
        # 临时设置环境变量指向Cursor配置
        os.environ["CLAUDE_MCP_CONFIG"] = str(cursor_mcp_path)
        # 重新读取配置
        mcp = read_mcp_json()
    # 当前环境变量（优先从 launchctl 读取，其次是当前进程）
    env_baseurl = launchctl_getenv(ENV_BASE_URL) or os.environ.get(ENV_BASE_URL, "")
    env_apikey = launchctl_getenv(ENV_AUTH_TOKEN) or os.environ.get(ENV_AUTH_TOKEN, "")
    env_apikey_masked = mask_key(env_apikey)
    # 允许通过环境变量在测试中注入固定状态
    forced = os.environ.get("FORCE_CLAUDE_STATUS", "").strip()
    if forced:
        try:
            status = json.loads(forced)
        except Exception:
            status = get_claude_code_status()
    else:
        status = get_claude_code_status()
    return render_template(
        "index.html",
        accounts=accounts,
        mcp_raw=json.dumps(mcp, ensure_ascii=False, indent=2),
        claude_installed=status["installed"],
        claude_current_version=status["current_version"],
        claude_latest_version=status["latest_version"],
        claude_needs_upgrade=status["needs_upgrade"],
        claude_source=status["source"],
        claude_vscode_ext_id=status["vscode_ext_id"],
        env_baseurl=env_baseurl,
        env_apikey=env_apikey_masked,
        env_file_path=str(ENV_FILE_PATH),
    )


@app.route("/add", methods=["POST"])  # 简洁起见，直接表单提交
def add_account():
    baseurl = request.form.get("baseurl", "").strip()
    apikey = request.form.get("apikey", "").strip()
    if not baseurl or not apikey:
        flash("请填写 baseurl 与 apikey", "danger")
        return redirect(url_for("index"))

    new_account = Account(baseurl=baseurl, apikey=apikey)
    db.session.add(new_account)
    db.session.commit()
    flash("账号添加成功", "success")
    return redirect(url_for("index"))


@app.route("/edit/<int:account_id>", methods=["GET", "POST"])
def edit_account(account_id: int):
    account = Account.query.get_or_404(account_id)
    if request.method == "POST":
        baseurl = request.form.get("baseurl", "").strip()
        apikey = request.form.get("apikey", "").strip()
        if not baseurl or not apikey:
            flash("请填写 baseurl 与 apikey", "danger")
            return redirect(url_for("edit_account", account_id=account_id))
        account.baseurl = baseurl
        account.apikey = apikey
        db.session.commit()
        flash("账号更新成功", "success")
        return redirect(url_for("index"))
    return render_template("edit.html", account=account)


@app.route("/delete/<int:account_id>")
def delete_account(account_id: int):
    account = Account.query.get_or_404(account_id)
    db.session.delete(account)
    db.session.commit()
    flash("账号删除成功", "success")
    return redirect(url_for("index"))


@app.route("/set_default/<int:account_id>")
def set_default(account_id: int):
    account = Account.query.get_or_404(account_id)
    # 新策略：设置环境变量（launchctl + shell env 文件）
    apply_env_settings(account.baseurl, account.apikey)
    flash("已设置为默认账号（环境变量已写入，且生成了 shell 环境文件）", "success")
    return redirect(url_for("index"))


@app.route("/edit_mcp", methods=["GET", "POST"])
def edit_mcp():
    if request.method == "POST":
        raw = request.form.get("mcp_raw", "")
        try:
            data = json.loads(raw) if raw.strip() else {}
            write_mcp_json(data)
            flash("Claude Code 配置已保存", "success")
            return redirect(url_for("index"))
        except json.JSONDecodeError as e:
            flash(f"JSON 格式错误: {e}", "danger")
            # 回显用户输入
            return render_template("edit_mcp.html", mcp_raw=raw)

    current = read_mcp_json()
    return render_template(
        "edit_mcp.html",
        mcp_raw=json.dumps(current, ensure_ascii=False, indent=2),
        mcp_path=str(Path.home() / ".claude.json"),
    )


@app.route("/check_claude")
def check_claude():
    installed, version = get_claude_version()
    if installed:
        flash(f"Claude Code 已安装，版本：{version}", "info")
    else:
        flash("Claude Code 未安装", "warning")
    return redirect(url_for("index"))


@app.route("/install_claude")
def install_claude():
    # 优先安装 VSCode 扩展
    if command_exists("code"):
        # 优先 anthropic.claude-code，失败回退 anthropic.claude
        code_rc, out, err = run_command_safely(["code", "--install-extension", "anthropic.claude-code"])  # noqa: S603
        if code_rc != 0:
            code_rc, out, err = run_command_safely(["code", "--install-extension", "anthropic.claude"])  # noqa: S603
        if code_rc == 0:
            flash("已安装 VSCode 扩展：Claude Code", "success")
            return redirect(url_for("index"))
        else:
            flash(f"安装 VSCode 扩展失败：{err or out}", "warning")

    # 回退安装 CLI（需要 Node/npm）
    if command_exists("npm"):
        code_rc, out, err = run_command_safely(["npm", "-g", "install", "@anthropic-ai/claude-code"])  # noqa: S603
        if code_rc == 0:
            flash("已安装 CLI：claude-code", "success")
            return redirect(url_for("index"))
        else:
            flash(f"安装 CLI 失败：{err or out}", "danger")
            return redirect(url_for("index"))

    flash("未检测到 VSCode 或 npm，无法自动安装 Claude Code。", "danger")
    return redirect(url_for("index"))


@app.route("/update_claude")
def update_claude():
    status = get_claude_code_status()
    if not status["installed"]:
        flash("未安装 Claude Code，无需升级。", "info")
        return redirect(url_for("index"))

    if status["source"] == "vscode" and command_exists("code"):
        ext_id = status["vscode_ext_id"] or "anthropic.claude-code"
        code_rc, out, err = run_command_safely(["code", "--install-extension", ext_id, "--force"])  # noqa: S603
        if code_rc == 0:
            flash("VSCode 扩展已升级至最新。", "success")
        else:
            flash(f"VSCode 扩展升级失败：{err or out}", "danger")
        return redirect(url_for("index"))

    if status["source"] == "cli" and command_exists("npm"):
        code_rc, out, err = run_command_safely(["npm", "-g", "install", "@anthropic-ai/claude-code@latest"])  # noqa: S603
        if code_rc == 0:
            flash("CLI 已升级至最新。", "success")
        else:
            flash(f"CLI 升级失败：{err or out}", "danger")
        return redirect(url_for("index"))

    flash("未找到可用的升级方式（请确认已安装 VSCode 或 npm）。", "warning")
    return redirect(url_for("index"))


@app.route("/install_ccui")
def install_ccui_route():
    path = install_ccui()
    # 确保 ~/.local/bin 在 PATH 且被 launchctl 继承
    _, appended = ensure_local_bin_on_path()
    on_path, where = is_ccui_on_path()
    if on_path:
        msg = f"ccui 已安装并可用：{where}"
        if appended:
            msg += f"（已写入 PATH 配置：{appended}）"
        flash(msg, "success")
    else:
        flash(f"ccui 已安装在 {path}，已尝试写入 PATH，但当前会话可能未生效。请新开一个终端再试。", "warning")
    return redirect(url_for("index"))


if __name__ == "__main__":
    ensure_db_initialized()
    # 启动时自动确保安装 CLI 与 ccui（测试模式不执行）
    if os.environ.get("FLASK_TEST") != "1":
        ensure_cli_and_ccui_installed()
    # 允许通过环境变量控制测试/端口/调试
    host = os.environ.get("HOST", "127.0.0.1")
    port_env = os.environ.get("PORT")
    try:
        port = int(port_env) if port_env else 5000
    except ValueError:
        port = 5000

    debug_flag_env = os.environ.get("FLASK_DEBUG")
    if debug_flag_env is not None:
        debug_flag = debug_flag_env == "1"
    else:
        debug_flag = True

    if os.environ.get("FLASK_TEST") == "1":
        debug_flag = False

    use_reloader_env = os.environ.get("FLASK_USE_RELOADER")
    if use_reloader_env is not None:
        use_reloader = use_reloader_env == "1"
    else:
        use_reloader = debug_flag

    # 启动后台刷新线程（测试模式关闭；避免 debug 重载双启）
    if os.environ.get("FLASK_TEST") != "1":
        should_start_thread = (not debug_flag) or (os.environ.get("WERKZEUG_RUN_MAIN") == "true")
        if should_start_thread:
            t = threading.Thread(target=background_latest_version_refresher, args=(600,), daemon=True)
            t.start()

    app.run(host=host, port=port, debug=debug_flag, use_reloader=use_reloader)


