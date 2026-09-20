# Architecture

## Request flow

1. User clicks **Investigate** on an incident. The API creates a `run` and pushes its id to Redis `runs:queue`.
2. The worker pops the id, starts the LangGraph run (Postgres checkpointer) and emits an event at every node and tool call.
3. Events are stored in `run_events` and published on Redis channel `run:{id}`.
4. The API relays them to the browser over SSE (`GET /runs/{id}/stream`); the UI renders the live checklist.
5. At `create_github_issue` the graph interrupts. The UI shows the report with **Approve / Edit / Reject**.
6. On approval the API pushes the id to `runs:resume`; the worker resumes and creates the GitHub issue.

## Graph

```
intake -> triage -> generate_hypotheses
                          |
            +-----> select_hypothesis
            |             |
            |       gather_evidence  (MCP tool calls)
            |             |
            |       evaluate  (confirm / refute / inconclusive)
            |             |
            +--- enough evidence? --- no ---+
                          | yes
                    propose_fix -> write_report -> [INTERRUPT] -> create_github_issue
```

Stopping rule: one hypothesis confirmed with evidence from >=2 independent tools, or budget exhausted.

## Services (docker compose)

| service | role |
|---|---|
| postgres (pgvector) | investigator DB + `checkout` DB for the target app |
| redis | run queue + pub/sub |
| target-app | checkout service, structured logs, /metrics, fault injector |
| mcp-server | read-only tools: logs, metrics, DB, git, deploy events, past incidents |
| api | REST + SSE |
| worker | executes graph runs |
| web | Next.js UI |
| otel-collector + jaeger | traces per node / LLM call / tool call |
