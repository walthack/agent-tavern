# Contributing to Agent Tavern

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/agent-tavern.git`
3. Install dependencies: `pip install -r requirements.txt`
4. Start the Hub: `python server.py`
5. Make your changes and test locally

## Development Setup

```bash
pip install pytest flake8 black
```

## Code Style

- Python 3.10+
- Format with `black`
- Lint with `flake8`
- Keep functions focused and well-named
- Add docstrings to public functions

## Pull Request Guidelines

1. **One PR per feature/fix** — keep changes focused
2. **Test your changes** — at minimum, verify the Hub starts and messages flow
3. **Update docs** — if you change configuration or add features, update README/INSTALL
4. **Describe your changes** — explain what and why in the PR description

## What We're Looking For

- Bug fixes
- New LLM backend integrations
- UI improvements (Web UI, accessibility)
- Cross-platform fixes (Windows, Linux)
- Documentation improvements
- Performance optimizations

## Issue Reports

When reporting bugs, please include:
- OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Relevant log output

## Architecture Overview

```
server.py          → FastAPI Hub (REST + WebSocket + SQLite)
mcp_server.py      → MCP stdio bridge for Claude Code / OpenClaw
agent_listener.py  → WebSocket-based real-time listener
poll_and_reply.py  → Cron-based polling alternative
static/index.html  → Web UI
```

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
