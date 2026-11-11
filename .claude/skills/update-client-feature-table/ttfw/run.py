#!/usr/bin/env python3
# usage: run.py CLIENT_DISPLAY RUNS -- client command...
# times each run from executing the client until the 'ttfw-xterm' window is mapped on CLIENT_DISPLAY
import os
import signal
import statistics
import subprocess
import sys
import time

here = os.path.dirname(os.path.abspath(__file__))
disp, runs = sys.argv[1], int(sys.argv[2])
cmd = sys.argv[sys.argv.index("--") + 1:]
env = dict(os.environ, DISPLAY=disp)
res = []
for i in range(runs):
    w = subprocess.Popen([sys.executable, os.path.join(here, "watch.py"), "ttfw-xterm"],
                         env=env, stdout=subprocess.PIPE, text=True)
    assert w.stdout.readline().strip() == "ready"
    t0 = time.monotonic()
    with open(os.environ.get("TTFW_LOG", os.devnull), "a") as log:
        c = subprocess.Popen(cmd, env=env, stdout=log, stderr=log, start_new_session=True)
    try:
        out, _ = w.communicate(timeout=30)
        res.append(float(out.strip()) - t0)
    except subprocess.TimeoutExpired:
        w.kill()
        res.append(float("nan"))
    os.killpg(c.pid, signal.SIGTERM)
    try:
        c.wait(5)
    except subprocess.TimeoutExpired:
        os.killpg(c.pid, signal.SIGKILL)
        c.wait()
    # let the server clean up the previous connection
    time.sleep(3)
ms = [round(r * 1000) if r == r else -1 for r in res]
print(cmd[0], "runs(ms):", ms, "median:", statistics.median(ms))
