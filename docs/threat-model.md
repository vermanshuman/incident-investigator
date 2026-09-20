# Threat model

## What the agent can do
- Read logs, metrics, database rows (read-only role), git history, deploy events, past incidents.
- Propose a fix as text.
- Create a GitHub issue **only after a human approves** the report.

## What it cannot do
- Write to any database (dedicated `investigator_ro` role, `default_transaction_read_only`, statement timeout, SQL parser rejects non-SELECT).
- Push code, merge, deploy, or change config.
- See the GitHub token or any provider secret: those live in the worker/API environment and are never placed in a prompt.

## Prompt injection
Log lines, commit messages and DB rows are attacker-controllable. Every tool output is wrapped in an
`<tool_output trust="untrusted">` block and the model is told to treat it as data. The write action is
gated by a LangGraph interrupt regardless of what the model outputs.

## Secrets and PII
A redaction pass runs on every tool output before it reaches the model (API keys, tokens, emails).

## Cost and runaway control
Per-run budgets for steps, tokens and wall-clock time; per-tool timeouts and retry limits; loop
detection on repeated identical tool calls.
