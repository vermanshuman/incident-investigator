# 90-second demo

Everything below runs from cassettes: no API key, no spend, and the same
result every take. Record with the browser at 1280x800 or wider.

**Before you start**

```bash
python dev.py
```

Leave it running. In a second terminal, start from a clean slate:

```bash
python fault.py reset --wipe
```

---

### 0:00 — the shop is healthy

Show `http://localhost:8080/health` → `{"status":"ok","version":"...","db_pool":"0/15"}`.
One line: *"This is the service under test. It has its own database, logs,
metrics and git history."*

### 0:10 — break it

```bash
python fault.py apply s01_null_check
```

Point at the output: a commit called *"Remove redundant shipping_address
validation"* was deployed, and 500s appear in the traffic summary.

### 0:20 — report the incident

In the browser: **Incidents → Report incident → "500s on checkout" → Create**.
Open it, leave the dropdown on **Replay: bad deploy**, click **Investigate**.

### 0:25–1:00 — watch it work

Narrate the timeline as it fills:

- it checks what shipped, finds the deploy
- it reads the logs and finds `AttributeError: 'NoneType' ... 'country'`
- hypotheses flip: **bad deploy → CONFIRMED**, the others → **REFUTED**

Click one "Gathered evidence" step. The panel shows the exact tool call, its
raw output, and the `source_ref`s that may be cited. Say: *"Every claim in the
report has to point at one of these. Anything else is dropped."*

### 1:00 — the report

Scroll to the root cause, the confidence, and **what it did not check** - it
says so itself. Mention cost: the status bar shows model calls, tokens and
`$ of $0.10 cap`.

### 1:10 — the gate

The **Approve / Edit / Reject** panel. Say: *"The agent stopped here. Opening
an issue is the only thing it can write, and it cannot do it alone."* Sign in,
click **Approve**. The issue link appears (or the dry-run note if no token is
set).

### 1:20 — the part people skip

Open `docs/eval-results.md`.

> Mean score **0.83** over 6 scenarios · external call right **6/6** · culprit
> right **3/6**

Say the honest line out loud: *"It gets the class of cause right five times
out of six, it never once blamed our code for a third-party outage, and twice
it named the commit without opening the diff — so it did not name the file.
That is in the table on purpose."*

---

## The two scenarios worth showing if you have longer

**The trap** — `s04_rotated_key`. Nothing was deployed, exactly like a vendor
outage, but the cause *is* our configuration. An agent that pattern-matches
"no deploy ⇒ not our bug" gets this wrong. This one does not.

**The dead end** — `s08_provider_outage`. The agent searches `/payment`, finds
nothing, checks metrics, discovers the errors are actually on `/checkout`, and
only then concludes external. Showing it recover is better than showing it be
right first time.

## If you want to show it live rather than replayed

Put a key in `.env` (`LLM_PROVIDER=gemini` on the free tier costs nothing),
pick **Live (calls the model)** in the dropdown, and expect a different path
each take - that is the honest version, and it is slower.
