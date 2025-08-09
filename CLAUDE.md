# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Flask-based web application that provides a local web UI for managing Claude Code accounts and MCP (Model Context Protocol) configurations. The app serves as a management interface for Claude Code authentication credentials and configuration files.

## Development Setup

### Dependencies Installation
```bash
# Install Python dependencies
pip install -r requirements.txt

# For development with virtual environment (recommended):
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

### Installation Methods
```bash
# Method 1: Run directly from source
python app.py

# Method 2: Install as package (for production/distribution)
pip install -e .
ccui-web  # Uses the installed package entry point
```

### Running the Application
```bash
# Development: Run from root directory
python app.py

# Production: Run installed package
ccui-web
```
The app runs on `http://127.0.0.1:5000` by default.

### Testing
```bash
# Run all tests
pytest -q

# Run specific test files
pytest tests/test_versions.py -v
pytest tests/test_playwright.py -v

# Run with coverage (if needed)
pytest --tb=short
```
Tests include:
- Version parsing and comparison logic (`test_versions.py`)
- Playwright-based UI functionality tests (`test_playwright.py`)

## Architecture

### Core Components
- **Flask App**: Dual structure with root `app.py` (development) and `ccui_web/app.py` (package)
- **SQLAlchemy Model**: `Account` model stores baseurl/apikey pairs in `accounts.db`
- **Templates** (`ccui_web/templates/`): Jinja2 HTML templates for the web interface
- **Environment Management**: Handles Claude Code environment variables and `ccui` script installation
- **Background Threading**: Automatic version checking and caching system

### Key Functionality
1. **Account Management**: Store/edit multiple Claude Code accounts (baseurl + API key pairs)
2. **Environment Variable Management**: Set `ANTHROPIC_BASE_URL` and `ANTHROPIC_AUTH_TOKEN` via launchctl and shell files
3. **MCP Configuration**: Edit `.claude/mcp.json` files (project-level or user-level)
4. **Version Management**: Check and upgrade Claude Code CLI/VSCode extension
5. **ccui Integration**: Install and configure the `ccui` wrapper script

### File Structure
- `app.py`: Development entry point (root level)
- `ccui_web/app.py`: Package entry point (production)
- `ccui_web/templates/`: HTML templates for web UI
- `accounts.db`: SQLite database (auto-created in `~/.ccui-web/` by default)
- `tests/`: pytest test suite
- `scripts/`: Windows-specific utility scripts
- `~/.claude-code-env`: Generated environment file
- `.claude/mcp.json` or `~/.claude/mcp.json`: MCP configuration

## Environment Variables

### Runtime Configuration
- `HOST`: Server host (default: 127.0.0.1)
- `PORT`: Server port (default: 5000)
- `FLASK_DEBUG`: Debug mode (default: True in dev)
- `FLASK_SECRET_KEY`: Session secret (default: "dev-secret-key")
- `FLASK_TEST`: Set to "1" to disable auto-installation and background threads

### Path Configuration
- `CLAUDE_ENV_FILE`: Override default environment file path
- `CLAUDE_MCP_CONFIG`: Override MCP config file path
- `CCUI_DATA_DIR`: Override default data directory (default: `~/.ccui-web`)
- `CCUI_DB_PATH`: Override database file location

### Testing/Demo Overrides
- `FORCE_LATEST_VERSION`: Override NPM version check
- `FORCE_CLAUDE_STATUS`: Inject fixed status JSON for testing

## Important Implementation Details

### Package Structure
The application has a dual structure to support both development and distribution:
- **Development**: Run `python app.py` from project root for local development
- **Package**: Install with `pip install -e .` and run `ccui-web` command
- Both entry points use the same Flask app from `ccui_web.app` module
- Templates are packaged within `ccui_web/templates/` for proper distribution

### Version Management System
The app implements semantic version parsing and comparison for Claude Code updates. It checks both CLI (`claude -v`) and VSCode extension versions, with NPM registry integration for latest version detection.

### Cross-Platform Environment Handling
- Uses `launchctl` on macOS for persistent environment variables
- Generates shell-compatible environment files
- Automatically configures PATH for `ccui` script

### MCP Configuration Priority
1. Project-level: `./.claude/mcp.json`
2. User-level: `~/.claude/mcp.json` 
3. Override via `CLAUDE_MCP_CONFIG` environment variable

## Security Considerations

- API keys are masked in the UI display
- Environment variables are written to user-accessible files only
- No network requests except to NPM/VSX registries for version checks
- SQLite database stores credentials locally (consider encryption for production)