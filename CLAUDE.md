# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

DaiFlow is a local AI-powered programming workbench that productizes the full development workflow (requirement → technical plan → task decomposition → coding → code review → merge request). It uses an in-process AI engine (Cody SDK) to understand project context and assist developers.

**Current status:** Core backend (FastAPI + SQLAlchemy + routers + services + state machines + runner abstraction) and frontend (React + Vite + WebSocket integration) are substantially implemented. Active development on runner backends, MCP server integration, and workflow refinements.

## Tech Stack

- **Frontend:** React 19 + TypeScript, built with Vite 6, react-router-dom v7
- **Backend:** Python 3.11+ with FastAPI (async), WebSocket for streaming
- **AI Engine:** Pluggable runner backends — Cody SDK (default, `pip install cody-ai`), Claude Code CLI, or Cursor IDE; see `docs/Cody_sdk.md` for Cody API
- **State Machines:** `transitions` library (AsyncMachine) for task/todo lifecycle enforcement
- **Database:** SQLite via SQLAlchemy async ORM (aiosqlite driver), Alembic for migrations
- **Local Storage:** `~/.daiflow/` directory for DB, sessions, projects, tasks (override with `DAIFLOW_HOME` env var)

## Development Commands

```bash
# Backend setup & run
pip install -r requirements.txt
pip install -e .                      # Install daiflow package in dev mode
uvicorn daiflow.main:app --reload --port 8000

# CLI entry point (after pip install -e .)
daiflow start                         # Starts server + auto-opens browser
daiflow start --port 9000 --no-browser

# Frontend
cd frontend
npm install
npm run dev          # Vite dev server with HMR
npm run build        # tsc + vite build

# Testing
pip install pytest pytest-asyncio httpx  # Test dependencies
pytest                                   # Run all tests
pytest tests/test_models.py              # Run a single test file
pytest tests/test_api_tasks.py -k "test_create_task"  # Run a single test

# Database migrations (Alembic)
alembic revision --autogenerate -m "description"  # Generate migration
alembic upgrade head                               # Apply migrations
# Note: alembic env.py auto-strips +aiosqlite from DATABASE_URL for sync Alembic

# Version bump
./scripts/bump-version.sh 0.6.0      # Update all version files at once
pip install -e .                      # Re-install so Python picks up new version
```

## Version Management

Single source of truth: `VERSION` file (semver format, e.g. `0.5.0`).

**`./scripts/bump-version.sh <version>` updates:**
1. `VERSION` — primary source
2. `frontend/package.json` — npm version
3. `frontend/package-lock.json` — lock file consistency
4. `electron/package.json` — desktop app version

**Python side** reads version dynamically — no file to edit:
- `pyproject.toml`: `dynamic = ["version"]` + `version = {file = "VERSION"}`
- `main.py`: `importlib.metadata.version("daiflow")` (reads installed package metadata)
- Requires `pip install -e .` after bump to refresh installed metadata

**Release checklist:**
1. `./scripts/bump-version.sh X.Y.Z`
2. `pip install -e .`
3. Verify: `python -c "from importlib.metadata import version; print(version('daiflow'))"`

## Environment Variables

- `DAIFLOW_HOME` — Override default `~/.daiflow/` data directory
- `DAIFLOW_LOG_RETENTION_DAYS` — Session log cleanup threshold (default: 30)
- `DAIFLOW_CORS_ORIGINS` — Comma-separated allowed CORS origins (default: localhost variants on ports 3000/8000)

## Architecture

```
Frontend (React SPA, Vite dev on :3000, proxies /api → :8000)
    ↕  HTTP REST + WebSocket
Backend (FastAPI)
    ↕                    ↕
Runner Backend        SQLite DB
(Cody / ClaudeCode
 / Cursor)
```

### Backend Module Organization

```
daiflow/
├── main.py              # FastAPI app, lifespan (crash recovery, log cleanup)
├── models.py            # SQLAlchemy ORM models + status enums
├── schemas.py           # Pydantic request/response schemas
├── database.py          # get_db (request-scoped), get_background_db (context manager)
├── config.py            # Constants, FILE_WRITE_TOOLS, language instructions
├── exceptions.py        # Domain exceptions (DaiFlowError hierarchy)
├── session_runner.py    # Unified AI execution → .jsonl logs → DB status → WS push
├── ws_manager.py        # WebSocket channel pub/sub manager
├── agent_executor.py    # Unified run_agent() entry point for all AI tasks
├── session_ids.py       # Session ID construction helpers
├── routers/             # FastAPI route handlers (9: projects, tasks, todos, sessions, jobs, skills, settings, ws, conversations)
├── services/            # Business logic (12: git, review, task, project, cody, chat, skill, mcp, runner, repo_monitor, settings, conversation)
├── agents/              # AgentConfig registry + definitions (init, plan, spec, review, todo_exec, todo_split)
├── runners/             # Runner backends (base protocol, cody_runner, claude_code_runner, cursor_runner)
├── workflow/            # State machines (task_machine, todo_machine) + orchestrator + pipeline
└── prompts/             # Centralized prompt templates for all AI tasks
```

### Agent Executor Pattern

All AI tasks (plan, todo split, todo exec, review) use a unified flow: router → `agent_executor.run_agent(agent_type, entity_id)` → builds `AgentContext` → `SessionRunner` executes the runner. Each agent type is registered in `daiflow/agents/__init__.py` as an `AgentConfig` with hooks for system prompt, `on_before_done`, and session ID construction. `get_agent_config(agent_type)` dispatches via registry lookup.

### Runner System

`daiflow/runners/` provides a pluggable backend abstraction (`AbstractAgentRunner` protocol in `base.py`):

- **CodyRunner** — wraps `AsyncCodyClient` (in-process Cody SDK)
- **ClaudeCodeRunner** — wraps Claude Code CLI subprocess
- **CursorRunner** — wraps Cursor IDE

Runner resolution uses a three-tier lookup (task → project → global settings default) via `runner_service.py`. `cody_service.build_runner()` instantiates the resolved runner type with its credentials. `RunnerConfig` records are stored in the `runner_configs` DB table.

### Exception Handling

Services raise domain exceptions (`NotFoundError`, `InvalidStateError`, `ConfigurationError`) inheriting from `DaiFlowError(message, status_code)`. Routers catch these and convert to HTTP responses. Never raise `HTTPException` from services.

### State Machines (transitions library)

`TaskWorkflow` and `TodoWorkflow` in `daiflow/workflow/` use the `transitions` library (`AsyncMachine`) to enforce valid state transitions. Invalid transitions raise `MachineError`. The orchestrator coordinates task-level state changes across stages.

**CRITICAL RULE: All Task/Todo status changes MUST go through the state machine (`TaskWorkflow` / `TodoWorkflow`). NEVER directly set `task.status` or `todo.status` — this bypasses validation and can leave the system in an inconsistent state.**

**Task failure recovery transitions:**
| Trigger | Source | Dest | When |
|---------|--------|------|------|
| `reset_init` | `initializing` | `created` | Init failed, user can retry |
| `reset_plan` | `planning` | `planning` | Plan generation failed, retry |
| `reset_todos` | `plan_locked` | `planning` | Todo decomposition failed, re-lock plan |
| `reset_review` | `reviewing` | `coding` | Review failed, back to coding |

### Startup Recovery

`main.py` lifespan runs `_recover_interrupted_sessions()` on startup: transitions RUNNING sessions → FAILED, auto-retries interrupted init pipelines, recovers stuck todos/tasks, and publishes WebSocket `status_change` events for reconnected clients.

### Core Workflow (5 Stages)

1. **Init** — Fetch code (copy repos to task dir, checkout branch) + sync skills; user confirms to proceed
2. **Plan** — AI generates technical plan; user discusses/adjusts, then locks
3. **Todo** — Locked plan auto-decomposed into sequential todos; user confirms to start coding
4. **Coding** — Each todo executed independently by AI; user reviews results
5. **Review** — Review all diffs, generate commit message, push MR

Frontend routes: `/devflow/:taskId/{init,plan,todo,coding,review}`. Each stage uses `isStageReadonly()` to become read-only once the task moves past it; users can click back to previous stages to review in readonly mode.

### Session Architecture (SessionRunner + WSManager)

All AI interactions share a unified pattern: **SessionRunner** executes Cody → writes logs to `.jsonl` → updates status in DB → pushes events via **WSManager** (WebSocket). Three data access patterns:
- `GET /api/sessions/{id}/status` — DB snapshot (survives restart)
- `GET /api/sessions/{id}/logs` — `.jsonl` file replay (survives restart)
- `WS /api/ws` — single multiplexed WebSocket connection for all real-time events

**WebSocket Protocol:** Single connection, channel-based pub/sub. Client sends `{"action": "subscribe", "channel": "session:task:42:plan"}` to receive events; sends `{"action": "chat", "id": "req_1", "chat_path": "plan", "entity_id": "abc", "message": "..."}` for bidirectional chat. Server pushes `{"channel": "...", "event": {...}}`.

**Two IDs to distinguish:**
- `session_id` — DaiFlow business ID (e.g. `task:42:plan`, `init:proj_1:frontend-structure`)
- `cody_session_id` — Cody SDK's internal UUID (stored in sessions table for traceability)

**Channel naming:**

- `session:{session_id}` — individual session event stream
- `project:init:{project_id}` — project init aggregation bus
- `chat:{request_id}` — ephemeral chat response stream (auto-cleaned on done)

### Conversations Module

A lightweight project-aware AI chat feature separate from the DevFlow workflow. Conversations copy project repos to `~/.daiflow/conversations/{conv_id}/code/` (removing `.git` to prevent accidental pushes — read-only context), sync skills, then enter `READY` state for open-ended chat. Uses the same `SessionRunner` + `WSManager` pattern as DevFlow stages. Channel naming: `project:init:{project_id}` (init bus), `session:{session_id}` (per-session events).

### Cody Session Strategy

- Project knowledge generation: independent Cody session per knowledge type (concurrent)
- Tech plan + todo decomposition: shared single Cody session (context continuity via `sessions` table lookup: `task_id` + `type="plan"`)
- Individual todo execution: independent Cody session per todo (plan.md as shared context)
- Code review: independent Cody session (tracked via `sessions` table: `task_id` + `type="review"`)

### Project Knowledge (Four-Layer Generation)

Layers execute serially (await), tasks within each layer run concurrently (asyncio.gather):

**Layer 1 (parallel):** Resource prep — Skill fetch + repo clone/pull
**Layer 2 (parallel, per-repo):** `frontend-structure`, `backend-structure`, `business-flow`, `component-usage`
**Layer 3 (parallel, cross-repo):** `module-overview`, `api-interaction`, `data-entity`, `dependencies`
**Layer 4:** Generate `project.md` index file
**Layer 5:** Generate `constitution.md` (reads `project.md` + all skill files; injected into every coding session)

Output: `~/.daiflow/projects/{project_id}/skills/{knowledge_type}/SKILL.md`

## Testing Patterns

- Tests use `pytest` with `asyncio_mode = auto` (see `pytest.ini`)
- `conftest.py` sets `DAIFLOW_HOME` to a temp directory before any daiflow imports
- DB tests use in-memory SQLite (`sqlite+aiosqlite:///:memory:`)
- API tests use `httpx.AsyncClient` with ASGI transport against the FastAPI app
- `get_db` and `get_background_db` are both overridden in the test `client` fixture — when adding new services that use `get_background_db`, add the module to the `_bg_db_modules` list in `conftest.py` (currently patches: `daiflow.database`, `daiflow.services.task_service`, `daiflow.services.project_service`, `daiflow.services.repo_monitor`, `daiflow.workflow.pipeline`)

## Key API Routes

| Category | Key Endpoints |
|----------|--------------|
| Settings | `GET/PUT /api/settings`, `GET /api/settings/check` |
| Projects | CRUD `/api/projects`, `POST .../init`, `GET .../init/sessions` |
| Tasks | CRUD `/api/tasks`, `POST .../confirm-init`, `POST .../lock-plan`, `POST .../start-coding`, `POST .../start-review` |
| Dev Flow | `POST /api/tasks/{id}/plan`, `POST .../todo`, `POST /api/todos/{id}/execute` |
| Sessions | `GET /api/sessions/{id}/status`, `GET .../logs` |
| WebSocket | `WS /api/ws` — subscribe to channels, real-time events, stage chat |
| Review | `GET /api/tasks/{id}/diff`, `POST /api/tasks/{id}/submit-mr` |
| Jobs | CRUD `/api/jobs`, `GET .../runs`, `POST .../trigger` |
| Skills | CRUD `/api/skills`, `POST .../link`, `DELETE .../unlink` |
| MCP Servers | CRUD `/api/mcp-servers`, `POST .../test` |
| Runner Configs | CRUD `/api/settings/runners` |
| Conversations | CRUD `/api/conversations`, `POST .../init` |

## Database Schema (14 tables)

Defined in `daiflow/models.py`. All primary keys use UUID hex strings (`uuid.uuid4().hex`).

- **runner_configs** — id, name, type (cody/claude_code/cursor), base_url, api_key, model, is_default
- **projects** — id, name, description, skill_names (JSON array string)
- **project_repos** — id, project_id (FK), git_url, local_path, repo_type (frontend/backend/custom), repo_type_label, description, master_hash
- **tasks** — id, name, project_id (FK), description, branch, prd, tech_plan, status (int), mr_info (JSON string)
- **todos** — id, task_id (FK), seq, title, description, status (int), cody_session_id, commit_before (JSON), commit_after (JSON), result
- **sessions** — session_id (PK, business ID), task_id (FK nullable), cody_session_id, type, ref_id, layer (1-4 for init, NULL otherwise), status (int), error, started_at, finished_at
- **jobs** — id, project_id (FK), type, enabled, interval, config (JSON)
- **job_runs** — id, job_id (FK), status (int), result (JSON), error, started_at, finished_at
- **settings** — key/value pairs: `cody_model`, `cody_base_url`, `cody_api_key`, `theme`, `language`
- **skills** — id, name, description, content (Markdown), is_builtin
- **project_skills** — id, project_id (FK), skill_id (FK), symlink_path
- **task_skills** — id, task_id (FK), skill_id (FK), symlink_path
- **mcp_servers** — id, name (unique), command, args (JSON), env (JSON), enabled
- **conversations** — id, name, project_id (FK), description, status (int), runner_id (FK nullable), created_at, updated_at

## Status Enums (IntEnum in models.py)

- **TaskStatus:** 0=CREATED, 1=INITIALIZING, 2=PLANNING, 3=PLAN_LOCKED, 4=TODO_READY, 5=CODING, 6=REVIEWING, 7=DONE
- **TodoStatus:** 0=PENDING, 1=RUNNING, 2=DONE, 3=FAILED, 4=SKIPPED
- **SessionStatus:** 0=WAITING, 1=RUNNING, 2=DONE, 3=FAILED
- **ConversationStatus:** 0=CREATING, 1=READY, 2=FAILED
- **JobRunStatus:** 0=RUNNING, 1=SUCCESS, 2=FAILED

## Key File Locations

- `docs/DaiFlow_技术方案.md` — Full technical specification (primary reference for implementation)
- `docs/DaiFlow_产品文档.md` — Product requirements document
- `docs/Cody_sdk.md` — Cody SDK API reference
- `demo/daiflow-ui/` — HTML/CSS UI prototypes (design reference)
- `demo/daiflow-ui/shared.css` — Design system (theme tokens, color palette, typography)

## Conventions

- Skill files use YAML frontmatter + Markdown body, with `user-invocable: false`
- All AI tasks go through SessionRunner → WSManager → WebSocket push
- Cody SDK StreamChunk types: `text_delta`, `thinking`, `tool_call`, `tool_result`, `done`, `compact`
- DaiFlow event types: above + `status_change` (converted from done), `plan_updated` / `todo_updated` / `code_updated` (file write detection per stage), `skill_loaded` (read_skill detection), `session_status` (init bus)
- Stage chats (Plan/Todo/Coding/Review) go through `WS /api/ws` chat action, shared pattern: `useStageChat` hook + `chat_service.prepare_stage_chat()` + `run_stage_chat()` backend generator (Init stage has no chat)
- Stage-specific updated events: `plan_updated` (push full content), `todo_updated` (push full content), `code_updated` (push null, frontend re-fetches diff), `skill_loaded` (push skill_name when Cody calls read_skill)
- Session logs persisted to `~/.daiflow/sessions/{session_id}.jsonl` for replay after restart
- Multi-repo support via `allowed_roots` in Cody client config
- Frontend routing: settings guard checks `/api/settings/check` before allowing access to main app
- Documentation is in Chinese (产品文档 = product doc, 技术方案 = tech spec)
- UI supports dark/light theme via `data-theme` attribute and CSS custom properties
- Fonts: Sora (sans-serif UI) + JetBrains Mono (code/monospace)
- Alembic migrations use `render_as_batch=True` (required for SQLite ALTER TABLE support)
- `config.py` file-write detection uses `FILE_WRITE_TOOLS` frozenset to identify Cody tool calls that modify files
