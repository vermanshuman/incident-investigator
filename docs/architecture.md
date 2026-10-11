# Architecture

## The shape of it

```
                    browser (Next.js)
                          │  SSE: one event per step
                          ▼
   alert ──API key──▶  FastAPI  ──queue──▶  agent run (worker thread)
                          │                      │
                          │                      ├─▶ LangGraph loop
                          │                      │     triage → hypotheses →
                          │                      │     {tool call, evaluate}* →
                          │                      │     report → ⏸ approval gate
                          │                      │
                          │                      └─▶ MCP tools (read only)
                          │                            logs · metrics · database
                          │                            deploys · commits · diffs
                          ▼                                      │
                   investigator DB                               ▼
          orgs · incidents · runs · events                  target app
          hypotheses · reports · audit                 (the "victim" service
                                                       + its git history)
```

Two databases on purpose. The investigator never writes to the thing it is
investigating, and the tools open the target's database read-only.

## The loop

```
intake → triage → generate_hypotheses → decide ⇄ run_tool
                                          │
                                          ├─ enough evidence? ─ no ─┘
                                          ▼ yes
                                     write_report
                                          ▼
                                  ⏸ INTERRUPT: approval
                                          ▼
                                   create_github_issue
```

`decide` merges two jobs into one model call - judge what the last tool
returned, then choose the next move - which is why a full investigation costs
6-9 calls rather than twice that.

**Stopping rule.** A hypothesis is confirmed only with evidence from both
sides: the symptom users hit (logs, metrics, database) *and* what changed
(deploys, commits, diffs). Two symptoms agreeing is not a root cause. When the
change tools find nothing shipped, that absence *is* the change-side evidence,
which is how "not our bug" stays reachable. If the model tries to stop
one-sided, the loop fetches the missing side itself - deterministically, with
no extra model call.

## State, not chat history

Each call sees a compact "case file": the incident, the hypothesis table, and
a ledger of what every tool returned. Nothing resends a transcript. That is
the main reason a run stays around 15K input tokens instead of ballooning.

## Trust

- Every claim must cite a `source_ref` that a tool actually returned. The
  validator drops anything else and records that it did.
- "Confirmed" without real evidence is downgraded, not believed.
- Tool output is wrapped and labelled untrusted, and secrets and emails are
  redacted before anything reaches the model.
- The one write action is not an agent tool. It runs from the trusted side
  after a human approves.

## Running a run

1. `POST /incidents/{id}/investigate` checks the org's plan limit, creates the
   run, and returns **202** immediately.
2. A worker thread executes the graph. Every event is persisted *and*
   published to an in-process bus whose interface is Redis pub/sub shaped.
3. The browser subscribes to `GET /runs/{id}/stream` with `last_seq`, so a
   refresh mid-run resumes rather than restarting.
4. At the gate the graph interrupts and its state is checkpointed to disk. The
   run can wait hours; approval may come from a different process.
5. On approval the graph resumes and files the issue; the decision, any edits,
   and the resulting issue are written to the audit trail.

## Deployment seams

Local development runs without Docker: SQLite for both databases, an
in-process event bus, and the agent in a worker thread. Three swaps make it a
deployment, and none of them touch the routers or the agent:

| Local | Deployed |
|---|---|
| SQLite | Postgres (`DATABASE_URL`) |
| in-process `EventBus` | Redis pub/sub - same `publish`/`subscribe` shape |
| worker thread | a worker process consuming a queue; `start_run` is the seam |
| SQLite checkpointer | Postgres checkpointer (`AGENT_CHECKPOINT_DB`) |

## Observability

With `OTEL_EXPORTER_OTLP_ENDPOINT` set (or `OTEL_CONSOLE=1`), each run emits a
span per node, model call and tool call, carrying tokens, cost and latency. A
replayed run traces too, which makes the shape easy to show without spending
anything.
