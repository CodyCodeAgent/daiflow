# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-07

### Added
- **Conversations module** — lightweight project-aware AI chat, separate from DevFlow workflow
- **Skill Center** — manage reusable skills, link/unlink to projects and tasks
- **Constitution drawer** — slide-in panel showing project context (project.md + skills) during DevFlow stages
- MCP server management UI and backend integration
- Runner config system with three-tier resolution (task → project → global)
- Multi-runner backend support: Cody SDK, Claude Code CLI, Cursor IDE
- Pluggable `AbstractAgentRunner` protocol for custom runner backends
- `ConversationStatus` enum (CREATING / READY / FAILED)

### Changed
- Replaced split-pane layout with slide-in drawer for project context panel
- Chat multi-turn context now correctly carries full history
- Polling todos during run-all for accurate progress tracking
- Project skills refactored: removed `skill_names` field, skills managed via `project_skills` join table

### Fixed
- Startup recovery now correctly handles interrupted init pipelines
- Session status correctly transitions on runner failure

## [0.6.0] - 2026-03-01

### Added
- Core DevFlow 5-stage workflow: Init → Plan → Todo → Coding → Review
- Four-layer concurrent project knowledge generation
- WebSocket single-connection multiplexed pub/sub (channel-based)
- Session architecture: SessionRunner + WSManager + JSONL log replay
- State machine enforcement via `transitions` library (AsyncMachine)
- Startup crash recovery for interrupted sessions
- Electron desktop app with auto Python venv management
- `deploy.sh` for server deployments (start / stop / update / logs)
- Alembic database migrations with SQLite batch mode
- `daiflow start` CLI entry point
