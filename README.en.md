# Multi-Agent AI Coding Assistant

[中文版本](./README.md)

![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-async-009688.svg)
![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-E92063.svg)
![OpenAI Compatible](https://img.shields.io/badge/OpenAI-compatible-412991.svg)
![Status Prototype](https://img.shields.io/badge/status-prototype-orange.svg)

> A FastAPI-based multi-agent AI coding system with both backend workflow APIs and an interactive terminal CLI, covering planning, human approval, code context analysis, code generation, review loops, and benchmark evaluation.

## Project Overview

This project implements a lightweight multi-agent coding workflow powered by four specialized agents:

- `Planner`: turns a natural-language requirement into a structured execution plan
- `Context`: reads real local files and analyzes dependencies
- `Coder`: generates structured code drafts from plan and context
- `Reviewer`: performs strict code review and drives iterative repair loops

The service exposes HTTP APIs for task creation, approval, status tracking, and SSE streaming; it also includes `cli.py` (Typer + Rich interactive client) and `benchmark.py` for end-to-end evaluation against a running server.

## Key Features

- Human-in-the-loop approval between planning and execution
- Secure local workspace file reading for code context analysis
- Structured LLM outputs validated by Pydantic models
- Bounded review-retry workflow for failed code reviews
- SSE event streaming for real-time model token and status output
- Interactive CLI client (Typer + Rich) with human-approval loop
- Built-in Tools (Function Calling) foundation for on-demand workspace inspection
- Async benchmark script for full pipeline evaluation

## Architecture

```mermaid
flowchart LR
    User[User / Benchmark / CLI Client] --> API[FastAPI API]
    API --> TaskStore[(SQLite Task DB)]
    API --> Workflow[Workflow Engine]
    API --> Stream[SSE Stream Manager]

    Workflow --> Planner[Planner Agent]
    Planner --> TaskStore
    Workflow --> Approval[Human Approval]
    Approval --> Workflow

    Workflow --> Context[Context Agent]
    Context --> Workspace[Workspace Files]
    Context --> Workflow

    Workflow --> Coder[Coder Agent]
    Coder --> TaskStore

    Workflow --> Reviewer[Reviewer Agent]
    Reviewer --> TaskStore
    Reviewer --> Workflow
    Workflow --> Stream

    Workflow --> Result[Completed / Failed Task]
```

## Current Runtime Characteristics

- Task state is persisted in a local SQLite database at `db/ai_coding.db`
- Generated code is stored in task results and written into `workspace` after review passes
- Real-time events are available from `/api/v1/tasks/{task_id}/stream`
- Historical tasks survive service restarts, but in-flight background jobs are not resumed after restart
- The current version should run with a single worker
- Best suited for local development, demos, and architecture validation

## Project Structure

```text
ai_coding_assistant/
├── app/
│   ├── api/               # HTTP routing layer
│   ├── agents/            # Planner / Context / Coder / Reviewer
│   ├── core/              # Configuration and LLM client
│   ├── models/            # Pydantic data models
│   ├── services/          # Workflow orchestration and SSE pub/sub
│   └── main.py            # FastAPI entrypoint
├── db/                    # SQLite database directory (ai_coding.db)
├── workspace/             # Code workspace read by AI
├── cli.py                 # Interactive CLI client (Typer + Rich)
├── benchmark.py           # Benchmark script
├── requirements.txt
├── .env.example
├── README.md
└── README.en.md
```

## API Overview

### Health Check

```http
GET /
```

Example response:

```json
{
  "status": "ok",
  "message": "AI Coding Assistant API is running"
}
```

### Create Task

```http
POST /api/v1/tasks/
Content-Type: application/json
```

Request body:

```json
{
  "requirement": "Add a GET API for product search with price-range and stock-status filters"
}
```

### Get Task Status

```http
GET /api/v1/tasks/{task_id}
```

### Subscribe to Task Events (SSE)

```http
GET /api/v1/tasks/{task_id}/stream
Accept: text/event-stream
```

### Approve Task

```http
POST /api/v1/tasks/{task_id}/approve
Content-Type: application/json
```

Request body:

```json
{
  "is_approved": true,
  "feedback": "Optional feedback when rejecting a plan"
}
```

## Environment Requirements

- Python 3.10+
- Conda or venv
- An available OpenAI-compatible model service
- An API key with access to the configured model

## Configuration

The project reads runtime configuration from `.env`. Start by copying the template:

```bash
cp .env.example .env
```

Key configuration fields:

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
OPENAI_MODEL=glm-5
APP_NAME=ai_coding_assistant
APP_ENV=development
LOG_LEVEL=INFO
WORKSPACE_DIR=workspace
```

Notes:

- `OPENAI_API_KEY`: required
- `OPENAI_BASE_URL`: OpenAI-compatible endpoint
- `OPENAI_MODEL`: must match the provider behind the endpoint
- `WORKSPACE_DIR`: local directory read by the Context agent

If you see `403 access_denied`, check the following first:

1. `OPENAI_BASE_URL` and `OPENAI_MODEL` belong to the same provider
2. The API key has access to the target model
3. The service has been restarted after editing `.env`

## Local Development Setup

### 1. Create and activate the environment

If you use Conda:

```bash
cd /home/wxr/proj/ai_coding_assistant
eval "$(conda shell.bash hook)"
conda create -n ai_coding python=3.10 -y
conda activate ai_coding
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Prepare configuration

```bash
cp .env.example .env
```

Then edit `.env` and fill in your own model service settings.

### 4. Start the service

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

After startup, verify the health endpoint:

```bash
curl http://127.0.0.1:8000/
```

## Quick Usage Examples

### Create a task

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/ \
  -H "Content-Type: application/json" \
  -d '{"requirement":"Write a Python script that reads a JSON file and prints the line count"}'
```

### Query a task

```bash
curl http://127.0.0.1:8000/api/v1/tasks/<task_id>
```

### Approve a task

```bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks/<task_id>/approve \
  -H "Content-Type: application/json" \
  -d '{"is_approved": true}'
```

### Subscribe to task stream (SSE)

```bash
curl -N http://127.0.0.1:8000/api/v1/tasks/<task_id>/stream
```

## Interactive CLI

After the API service is up, run the CLI in another terminal:

```bash
cd /home/wxr/proj/ai_coding_assistant
python cli.py
```

Banner shown on startup (`cli.py` ASCII banner):

```python
r"""
    ___    ____      ____          ___
   /   |  /  _/     / __ \____ ___/ (_)___  ____ _
  / /| |  / /______/ / / / __ `/ __  / / __ \/ __ `/
 / ___ |_/ /_____/ /_/ / /_/ / /_/ / / / / / /_/ /
/_/  |_/___/    /_____/\__,_/\__,_/_/_/ /_/\__, /
                                           /____/
"""
```

The CLI provides:

- Rich welcome screen and natural-language requirement input
- Plan rendering with human-in-the-loop approval
- Real-time streaming display of model tokens and task status
- Highlighted final state output (completed / failed)

Optional flags:

```bash
python cli.py --base-url http://127.0.0.1:8000 --planning-timeout 180 --final-timeout 480 --poll-interval 2
```

## Tool Calling System

The current version includes a built-in OpenAI Tools (Function Calling) foundation. The main implementation lives in:

- `app/core/tools.py`: tool registry, tool functions, and OpenAI tools schema
- `app/core/llm_client.py`: automatic tool-calling loop and final JSON normalization

Built-in tools:

- `list_directory(path)`: list files and subdirectories under a workspace-relative directory
- `read_file_content(file_path, start_line=1, end_line=-1)`: read a workspace-relative file with optional line slicing
- `run_shell_command(command)`: run a restricted shell command from the workspace root with a 15-second timeout

Agents currently using tools:

- `Context`
- `Coder`
- `Reviewer`

Implementation notes:

- Tool execution is strictly confined to `WORKSPACE_DIR`, with path traversal blocked
- Tool failures are returned to the model as `tool` message content so the model can recover
- To handle provider-specific compatibility issues, `llm_client` uses a two-phase strategy:
- Phase 1 allows the model to freely issue tool calls
- Phase 2 requests the final strict JSON output only after tool usage is complete
- It also normalizes provider-specific outputs such as `{"properties": {...}}` and tool-call payloads embedded in `message.content`

## Benchmark Usage

Make sure the service is already running, then execute the benchmark in another terminal:

```bash
cd /home/wxr/proj/ai_coding_assistant
eval "$(conda shell.bash hook)"
conda activate ai_coding
python benchmark.py
```

The script will:

- submit benchmark tasks
- poll until each task enters the approval phase
- auto-approve the task
- poll until the task is completed or failed
- print completion rate, median duration, and average reviewer findings

You can customize the following fields in [benchmark.py](./benchmark.py):

- `TASK_PROMPTS`
- `TOTAL_ROUNDS`
- `PLANNING_TIMEOUT_SECONDS`
- `FINAL_TIMEOUT_SECONDS`

## Deployment Guide

### Single-machine deployment

The current version is designed for single-machine, single-process deployment because:

- task state is persisted in SQLite, but background workflows are still launched via in-process `BackgroundTasks`
- multiple workers could share the database, but job execution and workspace file writes are still easier to keep deterministic with a single worker

For that reason, run it with a single worker:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Deploy with systemd

You can create `/etc/systemd/system/ai-coding-assistant.service` on a Linux server:

```ini
[Unit]
Description=AI Coding Assistant API
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/ai_coding_assistant
Environment="PYTHONUNBUFFERED=1"
ExecStart=/path/to/miniconda3/envs/ai_coding/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ai-coding-assistant
sudo systemctl start ai-coding-assistant
sudo systemctl status ai-coding-assistant
```

### Production considerations

If you plan to evolve this into a production-grade service, prioritize the following:

- introduce a more complete migration and task-audit strategy
- move background workflows to a job queue or message queue
- add per-agent timeout and cancellation control
- add generated-code rollback and audit capability
- add authentication, audit logging, rate limiting, and monitoring

## Current Limitations

- In-flight background tasks are not resumed across process restarts
- Generated output is still stored in the API task payload
- The Context agent reads files but does not commit Git changes
- End-to-end latency is directly impacted by model response time

## Future Directions

- migrate from SQLite to a production database such as PostgreSQL
- use object storage for intermediate artifacts
- add automatic code materialization and Git commit support
- improve observability across agent execution
- support multi-tenant scenarios and access control
