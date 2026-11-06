# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Development Tasks

### Quick Start
```bash
# Start the gateway with log rotation
bash scripts/start_with_logrotate.sh

# Run full acceptance tests
bash scripts/acceptance_full.sh

# Run client regression tests
bash scripts/regression_clients.sh

# Run stress test with 20 concurrent users
bash scripts/stress_test.sh 20

# Generate daily report
bash scripts/daily_report.sh
```

### Testing
- Run single test: `pytest tests/test_<component>.py -k <test_name>`
- Test discovery: `pytest --collect-only`

### Linting & Formatting
```bash
# Type checking
mypy app/

# Linting
pyright

# Formatting
black app/
```

## High-Level Architecture

**Core Pattern**: Transparent memory gateway that extends agent clients with infinite memory, infinite context, and document search capabilities. The architecture follows a layered pattern:

1. **Client Layer** (9+ supported clients) → 
2. **Protocol Adapters** (OpenAI/Anthropic/Responses) → 
3. **Pre-call Processing** (identity → memory → RAG → context assembly) → 
4. **Post-call Processing** (write-back queue) → 
5. **12 Core Endpoints** (model inference, memory storage, semantic search, etc.)

**Key Components**:
- `fastapi_gateway.py`: Main entry point
- `adapters/`: Protocol adapters and infrastructure integrations
- `app/use_cases/`: Core business logic (context engine, model routing)
- `app/workers/`: Background workers for write-back and indexing

**Data Flow**:
```
Client Request → Protocol Adapter → Pre-call RAG → Model → Post-call Write-Back → Memory Storage
```

**Storage Architecture**:
- **Long-term memory**: Mem0 + PostgreSQL
- **Semantic search**: Qdrant (vector DB)
- **Keyword search**: Meili (full-text search)
- **Model inference**: Local model server

## Important Directories

| Path | Purpose |
|---|---|
| `adapters/` | Protocol adapters and infrastructure hooks |
| `app/use_cases/` | Core business logic implementations |
| `app/workers/` | Background processing workers |
| `contracts/` | API contracts (zero third-party dependencies) |
| `scripts/` | Operational scripts |

## Endpoints of Note

| Method | Path | Purpose |
|---|---|
| POST | `/v1/chat/completions` | OpenAI-compatible endpoint |
| POST | `/v1/messages` | Anthropic-compatible endpoint |
| POST | `/v1/rag/documents` | Document upload for RAG |
| GET | `/v1/models` | Model listing |
| GET | `/metrics` | Prometheus metrics endpoint |

> ⚠️ If you have existing Codex/Gemini configurations, run `/import` to migrate them to Claude Code's format. This will handle MCP servers, slash commands, and other configurations safely.