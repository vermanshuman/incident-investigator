"""Start api, target-app and web together. Ctrl+C stops all.

    python dev.py

The target-app runs from ./target-repo (a seeded git repo, created on first
run). dev.py supervises it: when the fault injector touches
data/restart-target after a git checkout, dev.py restarts the service. That
restart is the "deploy".
"""

import os
import signal
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
TARGET_REPO = os.path.join(ROOT, "target-repo")
DATA_DIR = os.path.join(ROOT, "data")
TARGET_DB = os.path.join(DATA_DIR, "checkout.db")
RESTART_FLAG = os.path.join(DATA_DIR, "restart-target")
IS_WIN = os.name == "nt"

env = {
    **os.environ,
    "TARGET_REPO_PATH": TARGET_REPO,
    "TARGET_DATABASE_URL": "sqlite:///" + TARGET_DB.replace("\\", "/"),
    "TARGET_APP_URL": "http://localhost:8080",
    "TARGET_RESTART_FLAG": RESTART_FLAG,
}

SERVICES = {
    "api": ["uv", "run", "--directory", "apps/api", "uvicorn", "app.main:app",
            "--port", "8000", "--reload"],
    "target": ["uv", "run", "--directory", "apps/target-app", "uvicorn", "app.main:app",
               "--port", "8080", "--app-dir", TARGET_REPO],
    "web": ["npm", "--prefix", "apps/web", "run", "dev"],
}

procs: dict[str, subprocess.Popen] = {}
stopping = False


def start(name: str) -> None:
    procs[name] = subprocess.Popen(SERVICES[name], cwd=ROOT, env=env, shell=IS_WIN)
    print(f"[dev] started {name} (pid {procs[name].pid})")


def kill(p: subprocess.Popen) -> None:
    if p.poll() is not None:
        return
    if IS_WIN:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, check=False)
    else:
        p.send_signal(signal.SIGTERM)
    try:
        p.wait(timeout=10)
    except subprocess.TimeoutExpired:
        p.kill()


def ensure_target_repo() -> None:
    if os.path.isdir(os.path.join(TARGET_REPO, ".git")):
        return
    print("[dev] seeding target repo (first run) ...")
    subprocess.run(["uv", "run", "--directory", "apps/target-app", "inject-fault", "seed"],
                   cwd=ROOT, env=env, shell=IS_WIN, check=True)


def supervise_target() -> None:
    """Restart the target-app whenever the injector touches the restart flag."""
    while not stopping:
        time.sleep(0.5)
        if os.path.exists(RESTART_FLAG):
            os.remove(RESTART_FLAG)
            print("[dev] deploy requested: restarting target-app ...")
            kill(procs["target"])
            start("target")


try:
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(RESTART_FLAG):
        os.remove(RESTART_FLAG)
    ensure_target_repo()
    for name in SERVICES:
        start(name)
    threading.Thread(target=supervise_target, daemon=True).start()
    print("\n[dev] web http://localhost:3000  api http://localhost:8000/docs  target http://localhost:8080/docs")
    print("[dev] inject a fault:  python fault.py apply s01_null_check     (python fault.py list)")
    print("[dev] Ctrl+C to stop all\n")
    while True:
        time.sleep(1)
        if procs["api"].poll() is not None or procs["web"].poll() is not None:
            print("[dev] a service exited; shutting down")
            break
except KeyboardInterrupt:
    pass
finally:
    stopping = True
    for p in list(procs.values()):
        kill(p)
    print("[dev] stopped")
    sys.exit(0)
