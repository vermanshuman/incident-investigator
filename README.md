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

## Run the agent

Put an API key in `.env` (copy `.env.example`; `LLM_PROVIDER` = anthropic | openai | gemini), then:

```bash
python fault.py apply s01_null_check                 # break the shop
python investigate.py "POST /checkout returning 500s since a few minutes ago, ~30% of requests"
python evals.py                                      # all 3 cases: inject -> investigate -> score
```

The agent runs a hypothesis loop: triage (small model) -> 3-5 hypotheses -> repeat {one tool
call, evaluate} until a hypothesis is confirmed by 2 independent tools or a budget ends -> report.
Every citation must reuse a `source_ref` a tool actually returned; anything else is dropped by the
validator.

### Cost control

Measured: **~$0.08 per investigation** on Claude Sonnet 5 (6 LLM calls, ~21K tokens), and each run
prints its own cost.

| Control | Effect |
|---|---|
| `AGENT_MAX_COST_USD` (default `0.10`) | hard cap: the loop stops and reports what it has |
| `AGENT_MAX_STEPS` / `_TOKENS` / `_SECONDS` | step, token and wall-clock caps |
| prompt caching | the system prompt is cached, so repeat calls bill it at ~10% |
| `AGENT_CHEAP_REPORT=1` | write the report with the small model too |
| `LLM_MODEL=claude-haiku-4-5` | cheapest end-to-end |

### Free replay (demos, videos, UI work)

Record a run once, then reproduce it exactly with **zero API calls**:

```bash
python investigate.py --record cassettes/s08_provider_outage.jsonl "Payments failing since ..."
python investigate.py --replay cassettes/s08_provider_outage.jsonl "Payments failing since ..."
```

Replay prefers an exact prompt match and otherwise takes the next recording of the same step in
order, because prompts carry a timestamp and the growing evidence ledger and so never match byte
for byte. The tools still run live against the target app, so the evidence shown in a replay is
real; only the model's reasoning is played back. `cassettes/` is committed - that is what makes
the demo reproducible for anyone who clones the repo.

### Free path (no credit card)

`LLM_PROVIDER=gemini` with an AI Studio key runs on Google's free tier. A full investigation is
~14K tokens. Record it once and every later demo replays for free. Verified run on
`gemini-3.8-flash`: the provider-outage scenario, answered `external=true` with no commit blamed,
7 calls, $0.00.

## Phases

| # | Phase | Status |
|---|-------|--------|
| 0 | Foundation (repo, skeletons, CI) | done |
| 1 | Target app + fault injector (3 scenarios) | done |
| 2 | MCP tools (logs, metrics, DB, git, deploys) | done |
| 3 | Agent v1 (LangGraph loop, CLI run) + first evals | done (needs your live test) |
| 4 | Live UI (Redis events, SSE) | |
| 5 | Approval gate + GitHub issue + OAuth | |
| 6 | Knowledge base (pgvector) | |
| 7 | Full eval suite + dashboard | |
| 8 | Polish: OTel, docs, demo video | |

See [docs/architecture.md](docs/architecture.md) and [docs/threat-model.md](docs/threat-model.md).
