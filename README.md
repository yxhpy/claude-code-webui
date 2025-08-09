<div align="center">
  
# 🤖 Claude Code Manager

*一个优雅的本地 Web UI，轻松管理 Claude Code 账号与配置*

[![Python Version](https://img.shields.io/badge/python-3.9+-blue.svg)](https://python.org)
[![Flask](https://img.shields.io/badge/flask-3.0.3-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-lightgrey.svg)](https://github.com/your-org/your-repo)

</div>

## ✨ 特性

### 🔐 账号管理
- 支持多账号存储和快速切换
- 安全的 API 密钥管理（界面显示时自动掩码）
- 一键设置默认账号到环境变量

### 🌍 环境变量管理
- 自动配置 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_AUTH_TOKEN`
- macOS：集成 `launchctl` 用户环境
- 跨平台：生成 shell 环境文件 `~/.claude-code-env`

### ⚙️ MCP 配置编辑
- 智能配置文件优先级：项目级 → 用户级
- 支持 `${ANTHROPIC_*}` 环境变量引用
- Web 界面直接编辑 JSON 配置

### 🔄 版本管理
- 自动检测 Claude Code CLI 和 VSCode 扩展版本
- 后台定时获取最新版本信息
- 一键安装/升级功能

### 🚀 便捷启动
- `ccui` 包装脚本自动加载环境变量
- 项目目录历史记录
- 一键在指定目录启动 Claude Code

## 🚀 快速开始

### 系统要求
- Python 3.9+
- Node.js & npm（可选，用于 CLI 安装）
- VS Code（可选，用于扩展安装）

### 安装步骤

1. **克隆项目**
   ```bash
   git clone <repository-url>
   cd ccui-web
   ```

2. **创建虚拟环境**（推荐）
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # macOS/Linux
   # .venv\Scripts\activate   # Windows
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **启动服务**
   ```bash
   # 开发模式
   python app.py
   
   # 或安装为包
   pip install -e .
   ccui-web
   ```

5. **访问界面**
   打开浏览器访问 `http://127.0.0.1:5000`

## 📖 使用指南

### 基本使用流程

1. **添加账号**：在首页输入 Base URL 和 API Key
2. **设为默认**：点击账号旁的"设为默认"按钮
3. **安装工具**：点击"安装 Claude CLI"和"安装 ccui"
4. **开始使用**：在终端中直接使用 `ccui` 命令

### 命令示例

```bash
# 检查版本
ccui -v

# 启动对话
ccui chat

# 在指定目录使用
cd your-project
ccui
```

## 🏗️ 项目架构

### 核心组件
- **Flask 应用**：双入口结构，支持开发和打包部署
- **SQLAlchemy 模型**：账号信息存储
- **模板引擎**：响应式 Web 界面
- **后台任务**：版本检查和缓存

### 目录结构
```
ccui-web/
├── app.py                 # 开发入口
├── ccui_web/             # 包模块
│   ├── app.py            # 包入口
│   └── templates/        # Web 模板
├── tests/                # 测试套件
├── scripts/              # 实用脚本
└── requirements.txt      # 依赖列表
```

## 🧪 测试

运行完整测试套件：
```bash
pytest -q
```

运行特定测试：
```bash
# 版本管理测试
pytest tests/test_versions.py -v

# UI 功能测试
pytest tests/test_playwright.py -v
```

## 🔧 配置选项

### 环境变量

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `HOST` | 服务器监听地址 | `127.0.0.1` |
| `PORT` | 服务器端口 | `5000` |
| `FLASK_DEBUG` | 调试模式 | `True` |
| `CCUI_DATA_DIR` | 数据目录 | `~/.ccui-web` |
| `CLAUDE_ENV_FILE` | 环境文件路径 | `~/.claude-code-env` |
| `CLAUDE_MCP_CONFIG` | MCP 配置文件 | 自动检测 |

### 安装方法

**方法一：直接运行**
```bash
python app.py
```

**方法二：包安装**
```bash
pip install -e .
ccui-web
```

## 🛡️ 安全说明

- API 密钥仅存储在本地 SQLite 数据库
- 界面显示时自动掩码敏感信息
- 环境变量文件仅用户可访问
- 无外部网络请求（除版本检查）

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add some amazing feature'`)
4. 推送分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 📄 许可证

本项目基于 MIT 许可证开源 - 查看 [LICENSE](LICENSE) 文件了解详情。

---

<div align="center">
  <sub>Built with ❤️ using Flask and Claude Code</sub>
</div>
