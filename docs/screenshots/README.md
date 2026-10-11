# Screenshots

Captured from a local run with three investigations replayed from cassettes,
so they cost nothing to reproduce.

| file | what it shows |
|---|---|
| `01-live-run-approval.jpg` | the bad-deploy investigation: timeline, hypotheses flipping to CONFIRMED/REFUTED with their citations, the open evidence drawer, and the approval gate |
| `02-dashboard.jpg` | open incidents, runs awaiting approval, time to root cause, cost per run, and usage against the plan limit |
| `03-settings-plan-members.jpg` | organization switcher, usage meter, Free/Pro plans, members with roles and seat count |
| `04-incidents.jpg` | the incident list with severity and status |
| `05-external-cause-run.jpg` | the "not our bug" case - note the agent searches `/payment`, finds nothing, checks metrics, discovers the errors are really on `/checkout`, and only then concludes external |

To reproduce:

```bash
python dev.py
python fault.py reset --wipe
```

then report an incident in the UI and run it with the dropdown set to **Replay**.
