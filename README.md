# Claude Code 账号管理 Web UI（Flask）

一个轻量、便携的本地 Web UI，用于管理 Claude Code 账号（baseurl、apikey），支持：

- 设置默认账号（写入同目录 `mcp.json`）
- 在线编辑 `mcp.json`
- 检测 / 安装 / 升级 Claude Code

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

## 文件说明
- `app.py`：主应用（Flask + SQLite）
- `accounts.db`：自动生成的数据库文件
- `mcp.json`：默认账号等配置写入该文件
- `templates/`：前端模板

## 便携性
- 所有数据（`accounts.db`、`mcp.json`）均位于项目目录，便于复制/迁移
- 使用 `sys.executable -m pip` 安装/升级 `claude`，避免多 Python 版本冲突

## 注意
- `apikey` 以明文存储于本地 SQLite，仅用于个人本机。生产环境请改为安全存储方案（如加密）。
- 如需修改监听地址或端口，编辑 `app.py` 末尾 `app.run(host, port)`。
