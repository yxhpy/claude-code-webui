# Claude Code 账号管理 Web UI（Flask）

一个轻量、便携的本地 Web UI，用于管理 Claude Code 使用账号（baseurl、apikey），并辅助 MCP 配置与版本维护。

## 功能
- 环境变量管理：将 `baseurl`/`apikey` 写入 `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN`
  - 同时写入 `launchctl` 用户环境（macOS）与生成 `~/.claude-code-env`（`source` 即可生效）
- MCP 配置编辑：优先项目级 `./.claude/mcp.json`，否则用户级 `~/.claude/mcp.json`
  - 支持用 `${ANTHROPIC_*}` 在 MCP 配置中安全引用敏感信息
- 版本检测与安装升级：
  - 当前版本优先 `claude -v`
  - 最新版本来自 npm `@anthropic-ai/claude-code`（后台定时拉取并缓存）
  - 一键安装/升级 VSCode 扩展或 CLI
- ccui 一键启动脚本：`ccui` 会先加载 `~/.claude-code-env`，再执行 `claude`
  - 首页“安装 ccui”会自动写 PATH 到 `~/.zprofile`/`~/.zshrc` 并更新 `launchctl PATH`

## 快速开始
1) 准备 Python 3.9+
2) 可选：创建虚拟环境
```bash
python3 -m venv .venv
source .venv/bin/activate
```
3) 安装依赖
```bash
pip install -r requirements.txt
```
4) 启动服务
```bash
python app.py
```
访问 `http://127.0.0.1:5000`。

## 使用提示
- 在页面中新增账号后，点击“设为默认（写入环境变量）”，会生成/更新 `~/.claude-code-env`
- 新开一个终端后，直接执行：
```bash
ccui -v
ccui chat
```
- MCP 配置编辑入口：页面“编辑 mcp.json”（路径优先级：项目级 → 用户级；亦可通过 `CLAUDE_MCP_CONFIG` 覆盖）

## 目录说明
- `app.py`：主应用（Flask + SQLite）
- `templates/`：前端模板
- `tests/`：pytest + Playwright 测试
- `requirements.txt`：依赖
- `~/.claude-code-env`：自动生成的环境变量文件
- `./.claude/mcp.json` 或 `~/.claude/mcp.json`：MCP 配置

## 测试
```bash
pytest -q
```
包含：
- 语义版本解析与比较
- 状态聚合（VSCode 扩展 / CLI）
- Playwright 功能测试（按钮显隐）

## 注意
- `accounts.db` 仅存储你在页面输入的账号列表，便于切换；敏感值在本机使用，生产环境建议改为加密存储
- 如需修改监听地址或端口，编辑 `app.py` 末尾 `app.run(host, port)` 或设置环境变量 `HOST`/`PORT`
