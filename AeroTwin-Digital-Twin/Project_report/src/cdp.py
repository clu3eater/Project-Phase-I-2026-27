"""Tiny Chrome DevTools client used to capture the report's screenshots.

Usage:
  python cdp.py nav <url>
  python cdp.py js "<expression>"
  python cdp.py shot <out.png> [width height]
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import urllib.request

import websockets

PORT = 9333


def page_ws() -> str:
    tabs = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json").read())
    return next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"]


async def call(ws, method, params=None, _id=[0]):
    _id[0] += 1
    await ws.send(json.dumps({"id": _id[0], "method": method, "params": params or {}}))
    while True:
        m = json.loads(await ws.recv())
        if m.get("id") == _id[0]:
            if "error" in m:
                raise RuntimeError(m["error"])
            return m["result"]


async def main(argv):
    async with websockets.connect(page_ws(), max_size=2**28) as ws:
        cmd = argv[0]
        if cmd == "nav":
            await call(ws, "Page.navigate", {"url": argv[1]})
            await asyncio.sleep(3)
        elif cmd == "js":
            r = await call(ws, "Runtime.evaluate", {"expression": argv[1], "awaitPromise": True,
                                                    "returnByValue": True})
            print(json.dumps(r.get("result", {}).get("value"), indent=1)[:6000])
        elif cmd == "shot":
            w, h = (int(argv[2]), int(argv[3])) if len(argv) > 3 else (1600, 1000)
            await call(ws, "Emulation.setDeviceMetricsOverride",
                       {"width": w, "height": h, "deviceScaleFactor": 1.5, "mobile": False})
            await asyncio.sleep(1.5)
            r = await call(ws, "Page.captureScreenshot", {"format": "png"})
            open(argv[1], "wb").write(base64.b64decode(r["data"]))
            print("saved", argv[1])


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
