# Contributing to DaiFlow

## Getting Started

1. Fork the repo and clone your fork
2. Set up the dev environment:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cd frontend && npm install && cd ..
```

3. Run the backend and frontend in dev mode:

```bash
# Terminal 1
uvicorn daiflow.main:app --reload --port 8000

# Terminal 2
cd frontend && npm run dev
```

## Making Changes

- **Backend:** all AI tasks must go through `SessionRunner` → `WSManager` (never bypass the WebSocket push pipeline)
- **State changes:** always use `TaskWorkflow` / `TodoWorkflow` — never set `task.status` or `todo.status` directly
- **New services using `get_background_db`:** add the module to `_bg_db_modules` in `tests/conftest.py`
- **Database schema changes:** generate a migration with `alembic revision --autogenerate -m "description"`
- **New routers:** register in `daiflow/routers/__init__.py` and include in `daiflow/main.py`

## Running Tests

```bash
pytest                                          # all tests
pytest tests/test_api_tasks.py                  # single file
pytest tests/test_api_tasks.py -k "test_create" # single test
```

Tests use an in-memory SQLite database — no external services required.

## Pull Requests

- Keep PRs focused on a single concern
- Include tests for new backend logic
- Run `pytest` before opening a PR
- Describe *what* changed and *why* in the PR description

## Commit Style

```
<type>(<scope>): <description>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

## Reporting Issues

Please include:
- DaiFlow version (`daiflow --version` or check `VERSION` file)
- OS and Python version
- Steps to reproduce
- Relevant logs from `~/.daiflow/sessions/` or `daiflow.log`
