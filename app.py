from __future__ import annotations

import json
import os
import platform
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


# 基本路径与数据目录（确保可写）
BASE_DIR: Path = Path(__file__).resolve().parent
DATA_DIR: Path = Path(os.environ.get("CCUI_DATA_DIR", str(Path.home() / ".ccui-web")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH: Path = Path(os.environ.get("CCUI_DB_PATH", str(DATA_DIR / "accounts.db")))
# MCP 配置路径：优先项目级、再用户级；可通过 MCP_CONFIG 覆盖
ENV_FILE_PATH: Path = Path(os.environ.get("CLAUDE_ENV_FILE", str(Path.home() / ".claude-code-env")))

# Claude Code 环境变量名
ENV_BASE_URL = "ANTHROPIC_BASE_URL"
ENV_AUTH_TOKEN = "ANTHROPIC_AUTH_TOKEN"


# 统一使用包内模板目录，避免顶层 templates 冗余
PACKAGE_TEMPLATE_DIR = Path(__file__).resolve().parent / "ccui_web" / "templates"
app = Flask(__name__, template_folder=str(PACKAGE_TEMPLATE_DIR))
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
    """Write environment file compatible with the current platform."""
    if platform.system() == "Windows":
        # Windows batch file
        content = (
            f"@echo off\n"
            f"set {ENV_BASE_URL}={baseurl}\n"
            f"set {ENV_AUTH_TOKEN}={apikey}\n"
        )
        # Change extension to .bat for Windows
        env_file_path = ENV_FILE_PATH.with_suffix('.bat')
        env_file_path.write_text(content, encoding="utf-8")
    else:
        # Unix shell script
        content = (
            f"export {ENV_BASE_URL}={baseurl}\n"
            f"export {ENV_AUTH_TOKEN}={apikey}\n"
        )
        ENV_FILE_PATH.write_text(content, encoding="utf-8")


def launchctl_setenv(var: str, value: str) -> tuple[int, str, str]:
    """Set environment variable using platform-specific method."""
    if platform.system() == "Windows":
        return windows_setenv(var, value)
    else:
        return run_command_safely(["launchctl", "setenv", var, value])


def launchctl_getenv(var: str) -> str:
    """Get environment variable using platform-specific method."""
    if platform.system() == "Windows":
        return windows_getenv(var)
    else:
        code, out, _ = run_command_safely(["launchctl", "getenv", var])
        return out if code == 0 else ""


def windows_setenv(var: str, value: str) -> tuple[int, str, str]:
    """Set persistent environment variable on Windows using setx."""
    try:
        # Use setx to set user environment variable persistently
        result = subprocess.run(
            ["setx", var, value],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 127, "", "setx command not found"


def windows_getenv(var: str) -> str:
    """Get environment variable on Windows."""
    return os.environ.get(var, "")


def apply_env_settings(baseurl: str, apikey: str) -> None:
    # 写 shell 环境文件，便于用户 source 使用
    write_env_file(baseurl, apikey)
    # 尝试设置到 launchctl 用户环境，便于新启动的 GUI/终端应用继承
    launchctl_setenv(ENV_BASE_URL, baseurl)
    launchctl_setenv(ENV_AUTH_TOKEN, apikey)
    # 同时设置到当前Flask进程的环境变量中，以便页面立即显示更新
    os.environ[ENV_BASE_URL] = baseurl
    os.environ[ENV_AUTH_TOKEN] = apikey


# ---- ccui 工具安装与检测 ----
def generate_ccui_script() -> str:
    """Generate platform-specific ccui script."""
    if platform.system() == "Windows":
        # Windows batch script
        env_file_bat = ENV_FILE_PATH.with_suffix('.bat')
        script = f"""@echo off
if exist "{env_file_bat}" (
    call "{env_file_bat}"
)
claude %*
"""
    else:
        # Unix shell script
        script = f"""#!/bin/zsh
set -euo pipefail
ENV_FILE="${{CLAUDE_ENV_FILE:-{ENV_FILE_PATH}}}"
if [ -f "$ENV_FILE" ]; then
  . "$ENV_FILE"
fi
exec claude "$@"
"""
    return script


def _windows_ccui_candidate_dirs() -> list[Path]:
    """返回 Windows 下 ccui 安装候选目录列表（按优先顺序）。"""
    env_user = Path(os.environ.get("USERPROFILE", str(Path.home())))
    home_user = Path.home()
    candidates: list[Path] = []
    for base in {env_user, home_user}:
        candidates.extend([
            base / "AppData" / "Local" / "bin",
            base / "AppData" / "Roaming" / "npm",
            base / "bin",
            base / ".local" / "bin",
        ])
    candidates.append(DATA_DIR / "bin")
    return candidates


def install_ccui(target_dir: Path | None = None) -> Path:
    if target_dir is None:
        if platform.system() == "Windows":
            # Windows 固定写入到 %USERPROFILE%\AppData\Roaming\npm
            npm_roaming = Path.home() / "AppData" / "Roaming" / "npm"
            npm_roaming.mkdir(parents=True, exist_ok=True)
            target_dir = npm_roaming
        else:
            # Unix: 优先 ~/.local/bin 或 ~/bin
            candidate = Path.home() / ".local" / "bin"
            if not candidate.exists():
                candidate = Path.home() / "bin"
            candidate.mkdir(parents=True, exist_ok=True)
            target_dir = candidate
    else:
        target_dir.mkdir(parents=True, exist_ok=True)
    
    # Set appropriate file extension based on platform
    if platform.system() == "Windows":
        target_path = target_dir / "ccui.bat"
    else:
        target_path = target_dir / "ccui"
    
    print(f"DEBUG: 创建ccui文件: {target_path}")
    target_path.write_text(generate_ccui_script(), encoding="utf-8")
    
    # Set executable permissions on Unix systems
    if platform.system() != "Windows":
        target_path.chmod(0o755)
    
    return target_path


def is_ccui_on_path() -> tuple[bool, str]:
    """Check if ccui is available on PATH using platform-specific command."""
    if platform.system() == "Windows":
        # Windows: use 'where' command instead of 'which'
        code, out, _ = run_command_safely(["where", "ccui"])
        # Also check for ccui.bat
        if code != 0:
            code, out, _ = run_command_safely(["where", "ccui.bat"])
    else:
        # Unix: use 'which' command
        code, out, _ = run_command_safely(["which", "ccui"])
    return (code == 0 and bool(out)), out


def comprehensive_environment_check() -> dict:
    """全面的环境检验，返回详细的状态信息"""
    results = {
        "claude_cli": {"installed": False, "path": "", "version": "", "issues": []},
        "ccui": {"installed": False, "path": "", "issues": []},
        "npm": {"installed": False, "path": "", "version": "", "issues": []},
        "path_config": {"valid": False, "issues": []},
        "env_files": {"valid": False, "issues": []},
        "overall_status": "未检查"
    }
    
    # 1. 检查Claude CLI
    claude_path = find_command_path("claude")
    if claude_path:
        results["claude_cli"]["installed"] = True
        results["claude_cli"]["path"] = claude_path
        # 获取版本
        installed, version = get_cli_claude_code_version()
        if installed:
            results["claude_cli"]["version"] = version
        else:
            results["claude_cli"]["issues"].append("无法获取版本信息")
    else:
        results["claude_cli"]["issues"].append("Claude CLI未安装或不在PATH中")
    
    # 2. 检查ccui
    ccui_installed, ccui_path = is_ccui_on_path()
    if ccui_installed:
        results["ccui"]["installed"] = True 
        results["ccui"]["path"] = ccui_path
        
        # 检查ccui脚本内容是否正确
        possible_paths = []
        if platform.system() == "Windows":
            possible_paths = [
                Path.home() / "AppData" / "Local" / "bin" / "ccui.bat",
                Path.home() / "bin" / "ccui.bat",
                Path.home() / ".local" / "bin" / "ccui.bat"
            ]
        else:
            possible_paths = [
                Path.home() / ".local" / "bin" / "ccui",
                Path.home() / "bin" / "ccui"
            ]
            
        ccui_file_exists = False
        for path in possible_paths:
            if path.exists():
                ccui_file_exists = True
                try:
                    content = path.read_text(encoding="utf-8")
                    if platform.system() == "Windows":
                        if "claude %*" not in content:
                            results["ccui"]["issues"].append("ccui.bat脚本内容不完整")
                    else:
                        if "claude" not in content:
                            results["ccui"]["issues"].append("ccui脚本内容不完整")
                except Exception as e:
                    results["ccui"]["issues"].append(f"无法读取ccui文件: {e}")
                break
        
        if not ccui_file_exists:
            results["ccui"]["issues"].append("ccui文件不存在于预期位置")
    else:
        results["ccui"]["issues"].append("ccui未安装或不在PATH中")
    
    # 3. 检查npm
    npm_path = find_command_path("npm")
    if npm_path:
        results["npm"]["installed"] = True
        results["npm"]["path"] = npm_path
        # 获取npm版本
        code, out, err = run_command_safely([npm_path, "--version"])
        if code == 0:
            results["npm"]["version"] = out.strip()
        else:
            results["npm"]["issues"].append("无法获取npm版本")
    else:
        results["npm"]["issues"].append("npm未安装或不在PATH中")
    
    # 4. 检查PATH配置
    if platform.system() == "Windows":
        # 检查Windows PATH
        current_path = os.environ.get("PATH", "")
        ccui_dirs = [
            str(Path.home() / "AppData" / "Local" / "bin"),
            str(Path.home() / "bin"),
            str(Path.home() / ".local" / "bin")
        ]
        
        path_ok = False
        for ccui_dir in ccui_dirs:
            if Path(ccui_dir).exists() and any(ccui_dir.lower() in path_part.lower() for path_part in current_path.split(";")):
                path_ok = True
                break
        
        if path_ok:
            results["path_config"]["valid"] = True
        else:
            results["path_config"]["issues"].append("ccui目录不在PATH中")
            
        # 检查用户PATH注册表
        try:
            result = subprocess.run(
                ["reg", "query", "HKCU\\Environment", "/v", "PATH"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode != 0:
                results["path_config"]["issues"].append("无法读取用户PATH注册表")
        except Exception as e:
            results["path_config"]["issues"].append(f"PATH注册表检查失败: {e}")

        # 追加：检查 npm 全局目录是否在 PATH 中
        try:
            npm_global_dir = str(Path.home() / "AppData" / "Roaming" / "npm")
            current_user_path_reg = ""
            if 'result' in locals() and result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'PATH' in line and 'REG_' in line:
                        parts = line.split('    ')
                        if len(parts) >= 3:
                            current_user_path_reg = parts[3].strip()
                        break
            # 只要任一处包含即可视为 OK
            npm_ok = (
                (npm_global_dir.lower() in current_path.lower()) or
                (current_user_path_reg and npm_global_dir.lower() in current_user_path_reg.lower())
            )
            if not npm_ok:
                results["path_config"]["issues"].append("npm 全局目录未在 PATH 中: %USERPROFILE%\\AppData\\Roaming\\npm")
            # 综合评估：PATH 需同时满足 ccui 与 npm 目录
            results["path_config"]["valid"] = results["path_config"].get("valid", False) and npm_ok
        except Exception:
            # 保守不抛出
            pass
    
    # 5. 检查环境文件
    env_file_path = ENV_FILE_PATH
    if platform.system() == "Windows":
        env_file_path = ENV_FILE_PATH.with_suffix('.bat')
    
    if env_file_path.exists():
        try:
            content = env_file_path.read_text(encoding="utf-8")
            if platform.system() == "Windows":
                if "ANTHROPIC_BASE_URL" in content and "ANTHROPIC_AUTH_TOKEN" in content:
                    results["env_files"]["valid"] = True
                else:
                    results["env_files"]["issues"].append("环境文件缺少必要的环境变量")
            else:
                if "export ANTHROPIC_BASE_URL" in content and "export ANTHROPIC_AUTH_TOKEN" in content:
                    results["env_files"]["valid"] = True
                else:
                    results["env_files"]["issues"].append("环境文件缺少必要的环境变量导出")
        except Exception as e:
            results["env_files"]["issues"].append(f"无法读取环境文件: {e}")
    else:
        results["env_files"]["issues"].append("环境文件不存在")
    
    # 6. 综合状态评估
    total_issues = sum(len(component["issues"]) for component in results.values() if isinstance(component, dict) and "issues" in component)
    if total_issues == 0:
        results["overall_status"] = "正常"
    elif total_issues <= 2:
        results["overall_status"] = "轻微问题"
    else:
        results["overall_status"] = "严重问题"
    
    return results


def auto_fix_environment() -> dict:
    """自动修复环境问题"""
    fix_results = {
        "claude_cli": {"fixed": False, "message": ""},
        "ccui": {"fixed": False, "message": ""},
        "path_config": {"fixed": False, "message": ""},
        "env_files": {"fixed": False, "message": ""},
        "overall_success": False
    }
    
    print("DEBUG: 开始自动修复环境...")
    
    # 1. 修复Claude CLI
    claude_path = find_command_path("claude")
    if not claude_path:
        npm_path = find_command_path("npm")
        if npm_path:
            print("DEBUG: 尝试安装Claude CLI...")
            code, out, err = run_command_safely([npm_path, "install", "-g", "@anthropic-ai/claude-code"])
            if code == 0:
                fix_results["claude_cli"]["fixed"] = True
                fix_results["claude_cli"]["message"] = "Claude CLI安装成功"
                print("DEBUG: Claude CLI安装成功")
            else:
                fix_results["claude_cli"]["message"] = f"Claude CLI安装失败: {err}"
                print(f"DEBUG: Claude CLI安装失败: {err}")
        else:
            fix_results["claude_cli"]["message"] = "npm未找到，无法安装Claude CLI"
    else:
        fix_results["claude_cli"]["fixed"] = True
        fix_results["claude_cli"]["message"] = "Claude CLI已存在"
    
    # 2. 修复ccui
    ccui_installed, ccui_path = is_ccui_on_path()
    if not ccui_installed:
        try:
            print("DEBUG: 安装ccui...")
            ccui_install_path = install_ccui()
            fix_results["ccui"]["fixed"] = True
            fix_results["ccui"]["message"] = f"ccui已安装到: {ccui_install_path}"
            print(f"DEBUG: ccui已安装到: {ccui_install_path}")
        except Exception as e:
            fix_results["ccui"]["message"] = f"ccui安装失败: {e}"
            print(f"DEBUG: ccui安装失败: {e}")
    else:
        fix_results["ccui"]["fixed"] = True
        fix_results["ccui"]["message"] = "ccui已存在"
    
    # 3. 修复PATH配置
    if platform.system() == "Windows":
        bin_success, bin_message = ensure_windows_bin_on_path()
        npm_success, npm_message = ensure_windows_npm_on_path()
        fix_results["path_config"]["fixed"] = bool(bin_success and npm_success)
        combined = "; ".join([m for m in [bin_message, npm_message] if m])
        fix_results["path_config"]["message"] = combined
        print(f"DEBUG: PATH修复结果: {combined}")
    else:
        success, message = ensure_local_bin_on_path()
        fix_results["path_config"]["fixed"] = success
        fix_results["path_config"]["message"] = message
    
    # 4. 修复环境文件（如果有账户的话）
    try:
        # 在当前应用上下文中执行数据库查询
        accounts = Account.query.all()
        if accounts:
            account = accounts[0]  # 使用第一个账户
            try:
                write_env_file(account.baseurl, account.apikey)
                apply_env_settings(account.baseurl, account.apikey)
                fix_results["env_files"]["fixed"] = True
                fix_results["env_files"]["message"] = "环境文件已更新"
                print("DEBUG: 环境文件已更新")
            except Exception as e:
                fix_results["env_files"]["message"] = f"环境文件更新失败: {e}"
                print(f"DEBUG: 环境文件更新失败: {e}")
        else:
            fix_results["env_files"]["message"] = "无账户信息，跳过环境文件修复"
            fix_results["env_files"]["fixed"] = True  # 没有账户不算失败
    except Exception as e:
        fix_results["env_files"]["message"] = f"数据库访问失败: {e}"
        print(f"DEBUG: 数据库访问失败: {e}")
    
    # 5. 综合评估
    fixed_count = sum(1 for result in fix_results.values() if isinstance(result, dict) and result.get("fixed", False))
    total_attempts = len([k for k, v in fix_results.items() if isinstance(v, dict) and k != "overall_success"])
    fix_results["overall_success"] = fixed_count >= total_attempts - 1  # 允许一个失败
    
    print(f"DEBUG: 修复完成，成功修复 {fixed_count}/{total_attempts} 项目")
    return fix_results


def ensure_cli_and_ccui_installed() -> None:
    """智能确保 CLI 和 ccui 安装，自动处理PATH问题"""
    print("DEBUG: 开始检查和安装Claude CLI和ccui...")
    
    # 1) 检查 claude CLI 是否可用
    claude_path = find_command_path("claude")
    if not claude_path:
        print("DEBUG: Claude CLI未找到，尝试安装...")
        # 尝试通过npm安装
        npm_path = find_command_path("npm")
        if npm_path:
            print(f"DEBUG: 使用npm安装Claude: {npm_path}")
            code, out, err = run_command_safely([npm_path, "install", "-g", "@anthropic-ai/claude-code"])
            if code == 0:
                print("DEBUG: Claude CLI安装成功")
            else:
                print(f"DEBUG: Claude CLI安装失败: {err}")
        else:
            print("DEBUG: npm未找到，无法自动安装Claude")
    else:
        print(f"DEBUG: Claude CLI已存在: {claude_path}")

    # 2) 安装 ccui 脚本
    installed, ccui_path = is_ccui_on_path()
    if not installed:
        print("DEBUG: ccui未找到，正在安装...")
        ccui_install_path = install_ccui()
        print(f"DEBUG: ccui已安装到: {ccui_install_path}")
        
        # 自动尝试修复PATH（仅在Windows上）
        if platform.system() == "Windows":
            success, message = ensure_windows_bin_on_path()
            if success:
                print(f"DEBUG: PATH配置成功: {message}")
            else:
                print(f"DEBUG: PATH配置失败: {message}")
    else:
        print(f"DEBUG: ccui已存在: {ccui_path}")


def ensure_windows_bin_on_path() -> tuple[bool, str]:
    """智能管理Windows PATH，支持多种ccui安装位置"""
    possible_dirs = [
        Path.home() / "bin",  # 更常见且通常在PATH中
        Path.home() / "AppData" / "Local" / "bin",
        Path.home() / ".local" / "bin"
    ]
    
    # 找到实际存在ccui.bat的目录
    ccui_dir = None
    for dir_path in possible_dirs:
        ccui_bat = dir_path / "ccui.bat"
        if ccui_bat.exists():
            ccui_dir = dir_path
            break
    
    if not ccui_dir:
        # 如果都不存在，优先检查哪个目录在PATH中
        current_path = os.environ.get("PATH", "").lower()
        path_parts = [p.lower() for p in current_path.split(";")]
        
        for dir_path in possible_dirs:
            if any(str(dir_path).lower() in part for part in path_parts):
                ccui_dir = dir_path
                print(f"DEBUG: 选择已在PATH中的目录: {ccui_dir}")
                break
        
        # 如果没有在PATH中的目录，使用默认的bin目录
        if not ccui_dir:
            ccui_dir = Path.home() / "bin"
            
        ccui_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"DEBUG: 使用ccui目录: {ccui_dir}")
    
    # 优先检查用户 PATH（注册表）是否已包含
    ccui_dir_str = str(ccui_dir)
    try:
        # 获取当前用户PATH（注册表持久化）
        result = subprocess.run(
            ["reg", "query", "HKCU\\Environment", "/v", "PATH"],
            capture_output=True,
            text=True,
            check=False
        )
        current_user_path = ""
        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                if 'PATH' in line and 'REG_' in line:
                    parts = line.split('    ')
                    if len(parts) >= 3:
                        current_user_path = parts[3].strip()
                    break
        if current_user_path and ccui_dir_str.lower() in current_user_path.lower():
            # 确保当前进程 PATH 也包含，便于本进程后续检测
            if ccui_dir_str.lower() not in os.environ.get('PATH','').lower():
                os.environ['PATH'] = f"{os.environ.get('PATH','')};{ccui_dir_str}"
            return True, f"目录已在用户PATH中: {ccui_dir}"

        # 构造新的PATH（基于用户PATH），避免重复添加
        new_path = f"{current_user_path};{ccui_dir_str}" if current_user_path else ccui_dir_str
        result = subprocess.run(
            ["setx", "PATH", new_path],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            # 同步更新当前进程 PATH，便于本次会话验证
            os.environ['PATH'] = f"{os.environ.get('PATH','')};{ccui_dir_str}"
            return True, f"已添加到用户PATH: {ccui_dir} (新终端生效)"
        else:
            return False, f"添加用户PATH失败: {result.stderr}"
    except Exception as e:
        return False, f"PATH配置异常: {e}"


def ensure_windows_npm_on_path() -> tuple[bool, str]:
    """确保 Windows 用户 PATH 中包含 npm 全局可执行目录（%USERPROFILE%\AppData\Roaming\npm）。
    返回 (success, message)。需要重新打开终端才会在新会话生效。
    """
    if platform.system() != "Windows":
        return True, "非 Windows 平台无需处理"
    try:
        npm_global_dir = Path.home() / "AppData" / "Roaming" / "npm"
        npm_global_dir.mkdir(parents=True, exist_ok=True)
        npm_dir_str = str(npm_global_dir)

        # 读取当前用户 PATH（注册表形式，持久化）
        result = subprocess.run(
            ["reg", "query", "HKCU\\Environment", "/v", "PATH"],
            capture_output=True,
            text=True,
            check=False,
        )
        current_user_path = ""
        if result.returncode == 0:
            for line in result.stdout.split("\n"):
                if "PATH" in line and "REG_" in line:
                    parts = line.split("    ")
                    if len(parts) >= 3:
                        current_user_path = parts[3].strip()
                    break
        # 如果已存在则直接返回
        if current_user_path and npm_dir_str.lower() in current_user_path.lower():
            return True, f"npm 全局目录已在用户 PATH 中: {npm_dir_str}"

        new_path = f"{current_user_path};{npm_dir_str}" if current_user_path else npm_dir_str
        result = subprocess.run(
            ["setx", "PATH", new_path],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True, f"已将 npm 全局目录添加到 PATH: {npm_dir_str} (新终端生效)"
        else:
            return False, f"添加 npm 目录到 PATH 失败: {result.stderr}"
    except Exception as e:
        return False, f"处理 npm 全局 PATH 异常: {e}"


def ensure_local_bin_on_path() -> tuple[bool, str]:
    """Ensure local bin directory is on PATH using platform-specific methods.
    
    Returns (processed?, message string)
    """
    if platform.system() == "Windows":
        return ensure_windows_bin_on_path()
    else:
        return ensure_unix_bin_on_path()


def ensure_unix_bin_on_path() -> tuple[bool, str]:
    """Ensure ~/.local/bin is on PATH (zsh configuration files) and launchctl PATH.
    
    Returns (processed?, appended file list string)
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
        # 在Windows上，显式设置PATH以确保能找到.cmd文件
        env = os.environ.copy()
        if platform.system() == "Windows":
            # 确保包含npm全局bin目录
            npm_global_path = Path.home() / "AppData" / "Roaming" / "npm"
            current_path = env.get("PATH", "")
            if str(npm_global_path) not in current_path:
                env["PATH"] = f"{npm_global_path};{current_path}"
        
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        return res.returncode, res.stdout.strip(), res.stderr.strip()
    except FileNotFoundError as e:
        return 127, "", str(e)
    except Exception as e:
        return 1, "", str(e)


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
    """Check if a command exists, handling Windows .cmd extensions."""
    commands_to_try = []
    
    if platform.system() == "Windows":
        # Windows: 尝试 .cmd 版本
        commands_to_try = [
            [f"{command}.cmd", "--version"],
            [command, "--version"]
        ]
    else:
        # Unix: 标准命令
        commands_to_try = [[command, "--version"]]
    
    for cmd in commands_to_try:
        code, _, _ = run_command_safely(cmd)
        if code == 0:
            return True
    
    return False


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


def find_command_path(command_name: str) -> str | None:
    """智能查找命令的完整路径，支持跨平台"""
    # 常见的安装位置
    search_paths = []
    
    if platform.system() == "Windows":
        # Windows常见路径
        search_paths = [
            Path.home() / "AppData" / "Roaming" / "npm",
            Path.home() / "AppData" / "Local" / "npm",
            Path("C:") / "Program Files" / "nodejs",
            Path("C:") / "Program Files (x86)" / "nodejs",
        ]
        
        # 要检查的文件扩展名
        extensions = [".cmd", ".bat", ".exe", ""]
    else:
        # Unix/Linux/macOS
        search_paths = [
            Path.home() / ".local" / "bin",
            Path.home() / "bin", 
            Path("/usr/local/bin"),
            Path("/usr/bin"),
            Path("/opt/homebrew/bin"),  # macOS Homebrew
        ]
        extensions = [""]
    
    # 首先尝试系统PATH
    for ext in extensions:
        cmd = f"{command_name}{ext}"
        try:
            result = subprocess.run(
                ["where" if platform.system() == "Windows" else "which", cmd],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')[0]  # 返回第一个找到的
        except:
            pass
    
    # 如果系统PATH找不到，手动搜索常见位置
    for search_path in search_paths:
        if not search_path.exists():
            continue
            
        for ext in extensions:
            candidate = search_path / f"{command_name}{ext}"
            if candidate.exists() and candidate.is_file():
                return str(candidate)
    
    return None


def get_cli_claude_code_version() -> tuple[bool, str]:
    """智能检测 Claude CLI，优先使用路径查找并包含多种回退。
    兼容测试环境对 run_command_safely 的打桩：即使找到绝对路径，也会继续尝试通用命令名。
    """
    
    commands_to_try: list[list[str]] = []

    # 1) 优先尝试绝对路径（如果能找到）
    claude_path = find_command_path("claude")
    if claude_path:
        commands_to_try.extend([
            [claude_path, "--version"],
            [claude_path, "-v"],
        ])

    # 2) 再尝试包名形式与通用命令名（便于测试桩命中）
    commands_to_try.extend([
        ["claude-code", "--version"],
    ])

    if platform.system() == "Windows":
        commands_to_try.extend([
            ["claude.cmd", "--version"],
            ["claude.cmd", "-v"],
        ])

    commands_to_try.extend([
        ["claude", "-v"],
        ["claude", "--version"],
    ])
    
    for cmd in commands_to_try:
        code, out, err = run_command_safely(cmd)
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
    # 1) CLI（优先使用 claude -v / claude-code --version 作为"当前版本"）
    cli_installed, cli_version = get_cli_claude_code_version()
    
    if cli_installed:
        # 以缓存的 npm scoped 包版本作为"最新"
        latest = get_cached_latest_version() or ""
        if not latest:
            latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
        needs = bool(latest and cli_version and compare_semver(cli_version, latest) < 0)
        result = {
            "installed": True,
            "source": "cli",
            "current_version": cli_version,
            "latest_version": latest,
            "needs_upgrade": needs,
            "vscode_ext_id": "",
        }
        return result

    # 2) VSCode 扩展（回退）
    installed, ext_id, current = get_vscode_claude_code_version()
    
    if installed:
        # 使用缓存的 npm scoped 包作为"最新"展示
        latest = get_cached_latest_version() or ""
        if not latest:
            latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
        needs = bool(latest and current and compare_semver(current, latest) < 0)
        result = {
            "installed": True,
            "source": "vscode",
            "current_version": current,
            "latest_version": latest,
            "needs_upgrade": needs,
            "vscode_ext_id": ext_id or "",
        }
        return result

    # 3) 未安装
    # 未安装时，也以缓存中的 npm scoped 包为"最新"展示
    fallback_latest = get_cached_latest_version() or ""
    if not fallback_latest:
        fallback_latest = get_npm_latest_version("@anthropic-ai/claude-code") or ""
    result = {
        "installed": False,
        "source": "",
        "current_version": "",
        "latest_version": fallback_latest,
        "needs_upgrade": False,
        "vscode_ext_id": "",
    }
    return result


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
    # 获取正确的环境文件路径（Windows用.bat扩展名）
    env_file_display = ENV_FILE_PATH.with_suffix('.bat') if platform.system() == "Windows" else ENV_FILE_PATH
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
        env_file_path=str(env_file_display),
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
    # 安装后如果不存在则按候选目录重试
    if platform.system() == "Windows" and not path.exists():
        for d in _windows_ccui_candidate_dirs():
            try:
                d.mkdir(parents=True, exist_ok=True)
                path = install_ccui(target_dir=d)
                if path.exists():
                    break
            except Exception:
                continue

    # 修复 PATH（Windows 同时处理 ccui 目录与 npm 全局目录）
    if platform.system() == "Windows":
        # 仅保证 npm 全局目录（Roaming\npm）在 PATH，因 ccui 固定写入该目录
        _, _ = ensure_windows_npm_on_path()
    else:
        _, _ = ensure_local_bin_on_path()

    on_path, where = is_ccui_on_path()
    if on_path:
        msg = f"ccui 已安装并可用：{where}"
        flash(msg, "success")
    else:
        flash(f"ccui 已安装在 {path}，已尝试写入 PATH，但当前会话可能未生效。请新开一个终端再试。", "warning")
    return redirect(url_for("index"))


@app.route("/environment_check")
def environment_check_route():
    """API端点：返回环境检查结果"""
    try:
        results = comprehensive_environment_check()
        return results
    except Exception as e:
        return {"error": f"环境检查失败: {str(e)}", "overall_status": "检查失败"}


@app.route("/environment_fix", methods=["POST"])
def environment_fix_route():
    """API端点：执行环境修复"""
    try:
        results = auto_fix_environment()
        if results["overall_success"]:
            flash("环境修复完成！建议重启终端以使更改生效。", "success")
        else:
            issues = []
            for component, result in results.items():
                if isinstance(result, dict) and not result.get("fixed", True):
                    issues.append(f"{component}: {result.get('message', '未知错误')}")
            flash(f"环境修复部分完成，存在以下问题: {'; '.join(issues)}", "warning")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"环境修复失败: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/force_reinstall_ccui", methods=["POST"])
def force_reinstall_ccui_route():
    """强制重新安装ccui"""
    try:
        # 删除现有的ccui文件
        possible_paths = []
        if platform.system() == "Windows":
            possible_paths = [
                Path.home() / "AppData" / "Local" / "bin" / "ccui.bat",
                Path.home() / "bin" / "ccui.bat",
                Path.home() / ".local" / "bin" / "ccui.bat"
            ]
        else:
            possible_paths = [
                Path.home() / ".local" / "bin" / "ccui",
                Path.home() / "bin" / "ccui"
            ]
        
        deleted_files = []
        for path in possible_paths:
            if path.exists():
                path.unlink()
                deleted_files.append(str(path))
        
        # 重新安装
        ccui_path = install_ccui()
        
        # 修复PATH
        if platform.system() == "Windows":
            success, message = ensure_windows_bin_on_path()
        else:
            success, message = ensure_local_bin_on_path()
        
        if success:
            flash(f"ccui 已强制重新安装到 {ccui_path}。{message}", "success")
        else:
            flash(f"ccui 已强制重新安装到 {ccui_path}，但PATH配置可能有问题: {message}", "warning")
            
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"ccui强制重新安装失败: {str(e)}", "error")
        return redirect(url_for("index"))


@app.route("/launch_claude_terminal", methods=["POST"])
def launch_claude_terminal():
    """启动配置了环境的Claude Code命令行窗口"""
    try:
        # 获取当前默认账户（优先从当前进程环境变量，其次从launchctl，最后从数据库）
        env_baseurl = os.environ.get(ENV_BASE_URL, "") or launchctl_getenv(ENV_BASE_URL)
        env_apikey = os.environ.get(ENV_AUTH_TOKEN, "") or launchctl_getenv(ENV_AUTH_TOKEN)
        
        # 如果环境变量未设置，尝试使用数据库中的第一个账户
        if not env_baseurl or not env_apikey:
            accounts = Account.query.all()
            if accounts:
                account = accounts[0]
                env_baseurl = account.baseurl
                env_apikey = account.apikey
                # 立即应用这些设置
                apply_env_settings(env_baseurl, env_apikey)
            else:
                flash("没有可用的账户信息，请先添加账户并设为默认", "danger")
                return redirect(url_for("index"))
        
        # 准备环境变量
        env = os.environ.copy()
        env[ENV_BASE_URL] = env_baseurl
        env[ENV_AUTH_TOKEN] = env_apikey
        
        if platform.system() == "Windows":
            # Windows: 启动新的命令提示符窗口
            # 构建启动命令，设置环境变量并显示提示信息
            startup_script = f"""
echo Claude Code 环境已配置完成！
echo.
echo Base URL: {env_baseurl}
echo API Token: {env_apikey[:8]}...{env_apikey[-4:] if len(env_apikey) > 12 else env_apikey}
echo.
echo 正在设置PATH环境变量...
set PATH=%USERPROFILE%\\AppData\\Roaming\\npm;%PATH%
echo.
echo 测试 Claude CLI 可用性...
claude --version
echo.
echo 现在你可以直接使用以下命令:
echo   claude --version     （检查版本）
echo   claude               （启动交互模式）
echo   claude "your prompt" （直接发送提示）
echo.
echo 如果 claude 命令仍然无法找到，请尝试:
echo   %USERPROFILE%\\AppData\\Roaming\\npm\\claude.cmd --version
echo.
""".strip()
            
            # 将启动脚本写入临时批处理文件
            temp_bat = Path.home() / "claude_startup.bat"
            temp_bat.write_text(f'''@echo off
set ANTHROPIC_BASE_URL={env_baseurl}
set ANTHROPIC_AUTH_TOKEN={env_apikey}
set PATH=%USERPROFILE%\\AppData\\Roaming\\npm;%PATH%
{startup_script}
echo 按任意键删除此临时文件并继续...
pause >nul
del "%~f0" >nul 2>&1
''', encoding='utf-8')
            
            cmd = ["cmd", "/k", str(temp_bat)]
            subprocess.Popen(cmd, env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
            flash("已启动配置了Claude Code环境的命令提示符窗口", "success")
        else:
            # macOS/Linux: 尝试启动新的终端窗口
            if platform.system() == "Darwin":  # macOS
                # 使用AppleScript启动Terminal
                script = f'''
tell application "Terminal"
    activate
    do script "export {ENV_BASE_URL}={env_baseurl}; export {ENV_AUTH_TOKEN}={env_apikey}; echo 'Claude Code 环境已配置'; echo 'Base URL: {env_baseurl}'; echo '你可以直接使用 claude 命令'"
end tell
'''
                subprocess.run(["osascript", "-e", script], check=False)
                flash("已启动配置了Claude Code环境的Terminal窗口", "success")
            else:
                # Linux: 尝试常见的终端模拟器
                terminals = ["gnome-terminal", "konsole", "xterm", "x-terminal-emulator"]
                terminal_found = False
                
                for terminal in terminals:
                    try:
                        if terminal == "gnome-terminal":
                            cmd = [terminal, "--", "bash", "-c", f"export {ENV_BASE_URL}={env_baseurl}; export {ENV_AUTH_TOKEN}={env_apikey}; echo 'Claude Code 环境已配置'; echo 'Base URL: {env_baseurl}'; echo '你可以直接使用 claude 命令'; exec bash"]
                        elif terminal == "konsole":
                            cmd = [terminal, "-e", "bash", "-c", f"export {ENV_BASE_URL}={env_baseurl}; export {ENV_AUTH_TOKEN}={env_apikey}; echo 'Claude Code 环境已配置'; echo 'Base URL: {env_baseurl}'; echo '你可以直接使用 claude 命令'; exec bash"]
                        else:
                            cmd = [terminal, "-e", "bash", "-c", f"export {ENV_BASE_URL}={env_baseurl}; export {ENV_AUTH_TOKEN}={env_apikey}; echo 'Claude Code 环境已配置'; echo 'Base URL: {env_baseurl}'; echo '你可以直接使用 claude 命令'; exec bash"]
                        
                        subprocess.Popen(cmd, env=env)
                        flash(f"已启动配置了Claude Code环境的{terminal}窗口", "success")
                        terminal_found = True
                        break
                    except FileNotFoundError:
                        continue
                
                if not terminal_found:
                    flash("未找到可用的终端模拟器。请在系统中安装 gnome-terminal、konsole 或 xterm", "warning")
        
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"启动Claude命令行窗口失败: {str(e)}", "error")
        return redirect(url_for("index"))


def main() -> None:
    ensure_db_initialized()
    # 启动时自动进行全面的环境检验和修复（测试模式不执行）
    if os.environ.get("FLASK_TEST") != "1":
        print("DEBUG: 启动时进行环境检验和修复...")
        # 在应用上下文中执行环境检验和修复
        with app.app_context():
            check_results = comprehensive_environment_check()
            print(f"DEBUG: 环境检查完成，状态: {check_results['overall_status']}")
            
            if check_results['overall_status'] != "正常":
                print("DEBUG: 发现环境问题，开始自动修复...")
                fix_results = auto_fix_environment()
                if fix_results["overall_success"]:
                    print("DEBUG: 环境修复成功")
                else:
                    print("DEBUG: 环境修复部分失败，但不影响启动")
            else:
                print("DEBUG: 环境状态正常")
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


if __name__ == "__main__":
    main()


