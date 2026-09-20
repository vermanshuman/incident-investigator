"""Worker loop (plan section 6, request flow steps 2-3, 6).

- BLPOP run ids from Redis list `runs:queue`
- execute the LangGraph run with a Postgres checkpointer
- persist every node/tool event to run_events and PUBLISH to `run:{run_id}`
- on interrupt, mark the run awaiting_approval; resume when the API pushes
  an approval message onto `runs:resume`
"""

import os
import time

import redis

QUEUE = "runs:queue"
RESUME = "runs:resume"


def main() -> None:
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    print("worker: waiting for runs")
    while True:
        item = r.blpop([QUEUE, RESUME], timeout=5)
        if item is None:
            continue
        queue, run_id = item[0].decode(), item[1].decode()
        # TODO(phase 4): build_graph(checkpointer=PostgresSaver) and stream events
        print(f"worker: got {run_id} from {queue} (stub)")
        time.sleep(0.1)


if __name__ == "__main__":
    main()
