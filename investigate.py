"""Run the agent against the local target app (needs `python dev.py` + a key in .env).

    python investigate.py "POST /checkout returning 500s since a few minutes ago"
    python investigate.py --title "Payments failing" "Gateway timeouts since 09:41"
"""

from _local import main

main("agent", "investigate")
