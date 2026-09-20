# AI DevOps Incident Investigator

A hypothesis-driven agent that investigates production incidents like an on-call engineer.
It forms hypotheses, gathers evidence from logs, metrics, the database, past incidents and Git
history, rules causes out visibly, proposes a fix, and waits for human approval before opening a
GitHub issue. Every claim links to its evidence, and a built-in eval harness measures how often
the agent is right.

## Layout

```
apps/
  web/          Next.js + TypeScript dashboard, live run view
  api/          FastAPI: REST, SSE streaming, auth
  worker/       Background jobs that execute agent runs
  target-app/   The "victim" checkout service + fault injector
packages/
  agent/        LangGraph graph: state, nodes, prompts, schemas
  mcp-server/   Read-only investigation tools exposed over MCP
  evals/        Scripted incidents, runner, scoring
infra/          docker-compose, otel-collector config, DB init
docs/           architecture, threat model, eval results
```

## Quick start (local, no Docker)

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/) (`pip install uv`) and Node 20+.

```bash
python dev.py     # starts web (3000), api (8000), target-app (8080); Ctrl+C stops all
python test.py    # runs tests for every Python package
```

First run installs dependencies and seeds `target-repo/` (the victim's git history, 30 commits).

## Break the target app

```bash
python fault.py list                       # scenarios and their status
python fault.py apply s01_null_check       # commit culprit on a branch, deploy, send traffic
python fault.py apply s03_pool_exhaustion  # config change -> pool at 100%, QueuePool timeouts
python fault.py apply s08_provider_outage  # external outage: no commit, no deploy event
python fault.py reset                      # back to main (add --wipe to clear logs/metrics)
```

Evidence lands in `data/checkout.db`: `app_logs` (with stack traces), `metrics_samples`
(request_rate, error_rate, p95_latency_ms, db_pool_usage), `deploy_events`, and the culprit
commit is in `target-repo/` (`git log`, `git show <sha>`). `GET /health` reports the running SHA.

## Ask the investigation tools (what the agent will call)

```bash
python tools.py search_logs level=ERROR limit=5          # grouped error signatures + stack tails
python tools.py get_metrics metric=error_rate path=/checkout   # series + detected change points
python tools.py get_deploy_events                        # what shipped in the window
python tools.py list_commits limit=5                     # deployed branch, HEAD marked
python tools.py get_commit_diff sha=HEAD                 # the diff
python tools.py query_database "sql=select status, count(*) from orders group by status"
```

All tools are read-only: SQLite is opened `mode=ro`, SQL is parsed and must be a single
SELECT (row-capped, 5s timeout), git is read via `git log/show` only.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundation (repo, skeletons, CI) | done |
| 1 | Target app + fault injector (3 scenarios) | done |
| 2 | MCP tools (logs, metrics, DB, git, deploys) | done |
| 3 | Agent v1 (LangGraph loop, CLI run) + first evals | |
| 4 | Live UI (Redis events, SSE) | |
| 5 | Approval gate + GitHub issue + OAuth | |
| 6 | Knowledge base (pgvector) | |
| 7 | Full eval suite + dashboard | |
| 8 | Polish: OTel, docs, demo video | |

See [docs/architecture.md](docs/architecture.md) and [docs/threat-model.md](docs/threat-model.md).
