#!/usr/bin/env python3
# usage: cdp.py DEVTOOLS_PORT RUNS URL
# for each run: new browser context (empty cache) + new tab, navigate,
# then poll until the 'ttfw-xterm' title is in the page along with a window sized canvas
import asyncio
import json
import statistics
import sys
import time
import urllib.request

import websockets

port, runs, url = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
CHECK = "(document.body && document.body.innerText.includes('ttfw-xterm') && [...document.querySelectorAll('canvas')].some(c => c.width > 100 && c.height > 100))"


async def main():
    ver = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version"))
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=None) as ws:
        n = 0

        async def call(method, sid=None, **params):
            nonlocal n
            n += 1
            msg = {"id": n, "method": method, "params": params}
            if sid:
                msg["sessionId"] = sid
            await ws.send(json.dumps(msg))
            while True:
                r = json.loads(await ws.recv())
                if r.get("id") == n:
                    return r.get("result", r)
        res = []
        for i in range(runs):
            ctx = (await call("Target.createBrowserContext"))["browserContextId"]
            tid = (await call("Target.createTarget", url="about:blank", browserContextId=ctx))["targetId"]
            sid = (await call("Target.attachToTarget", targetId=tid, flatten=True))["sessionId"]
            t0 = time.monotonic()
            await call("Page.navigate", sid, url=url)
            t = float("nan")
            while time.monotonic() - t0 < 30:
                r = await call("Runtime.evaluate", sid, expression=CHECK, returnByValue=True)
                if r.get("result", {}).get("value"):
                    t = time.monotonic() - t0
                    break
                await asyncio.sleep(0.005)
            res.append(t)
            await call("Target.closeTarget", targetId=tid)
            await call("Target.disposeBrowserContext", browserContextId=ctx)
            await asyncio.sleep(2)
        ms = [round(r * 1000) if r == r else -1 for r in res]
        print(url, "runs(ms):", ms, "median:", statistics.median(ms))
asyncio.run(main())
