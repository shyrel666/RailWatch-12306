"""Read an already logged-in passenger page; output only structural evidence.

No passenger names, document fragments, page HTML, cookies or profile data are
serialized. A dedicated background tab is closed even when validation fails.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import websocket
from railwatch_order_page import READ_PASSENGER_BOOK_JS

PASSENGERS_URL = "https://kyfw.12306.cn/otn/view/passengers.html"


class CDP:
    def __init__(self, address):
        self.ws = websocket.create_connection(address, timeout=10, suppress_origin=True)
        self.sequence = 0

    def call(self, method, **params):
        self.sequence += 1
        self.ws.send(json.dumps({"id": self.sequence, "method": method, "params": params}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") != self.sequence:
                continue
            if "error" in message:
                raise RuntimeError("Browser command failed")
            return message.get("result", {})

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            raise RuntimeError("Page read failed")
        return result.get("result", {}).get("value")

    def close(self):
        self.ws.close()


def validate(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{port}/json/version", timeout=5) as response:
        version = json.load(response)
    browser = CDP(version["webSocketDebuggerUrl"])
    target = None
    page = None
    try:
        target = browser.call("Target.createTarget", url=PASSENGERS_URL, background=True)["targetId"]
        page = CDP(f"ws://127.0.0.1:{port}/devtools/page/{target}")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = page.evaluate("({ready:document.readyState,path:location.origin+location.pathname,"
                                  "table:!!document.querySelector('#content_list .order-item-table')})")
            if state and state.get("ready") == "complete":
                if "login" in urlparse(state.get("path", "")).path:
                    return {"recognized": False, "reason": "login_required"}
                if state.get("table"):
                    break
            time.sleep(0.25)
        if not state or state.get("path") != PASSENGERS_URL or not state.get("table"):
            return {"recognized": False, "reason": "page_not_ready"}
        # Reduce in the browser before transport: no account identity enters Python.
        expression = """(()=>{
          const result=(new Function(SCRIPT))();
          return {...result,items:result.items.map(person=>({
            ticket_type:person.ticket_type,type_source:person.type_source,
            verification:person.verification,has_masked_identity:!!person.identity_hint
          }))};
        })()""".replace("SCRIPT", json.dumps(READ_PASSENGER_BOOK_JS))
        return {"browser": version["Browser"], "path": PASSENGERS_URL,
                **page.evaluate(expression)}
    finally:
        try:
            if page:
                page.close()
            if target:
                browser.call("Target.closeTarget", targetId=target)
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    port = args.port
    if port is None:
        directory = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        port = int((directory / "railwatch-12306/chrome_profile_12306/DevToolsActivePort").read_text().splitlines()[0])
    if not 1 <= port <= 65535:
        raise ValueError("Invalid debugging port")
    result = validate(port)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("recognized") else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Exception messages can contain browser response bodies. Keep only type.
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1)
