"""Smoke the packaged Electron/preload/runtime contract using temporary user data.

Usage: python tests/packaged_smoke.py [--exe PATH]
Windows defaults to release/win-unpacked; macOS needs the app executable, e.g.
"release/mac-arm64/RailWatch 12306.app/Contents/MacOS/RailWatch 12306".
"""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen
import websocket

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from railwatch_config_contract import default_config
from railwatch_orders import OrderIntent, OrderJournal, OrderResult
from scripts.ci_keychain import use_test_keychain

EXE =ROOT / "release" / "win-unpacked" / "RailWatch 12306.exe"
IS_WINDOWS = sys.platform == "win32"


def isolated_user_data(tmp):
    """Return (runtime data directory, environment) for a temporary user profile."""
    if IS_WINDOWS:
        return Path(tmp) / "railwatch-12306", dict(os.environ, LOCALAPPDATA=tmp, APPDATA=tmp, NODE_OPTIONS="")
    # The Python runtime resolves ~/Library/Application Support through HOME.
    use_test_keychain(tmp)
    return (Path(tmp) / "Library" / "Application Support" / "railwatch-12306",
            dict(os.environ, HOME=tmp, NODE_OPTIONS=""))


def stop(process):
    if process.poll() is not None:
        return
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait(timeout=10)


def main():
    with tempfile.TemporaryDirectory(prefix="railwatch-package-test-") as tmp:
        # macOS temporary folders live under /var, a symlink to /private/var.
        tmp = os.path.realpath(tmp)
        data_dir, env = isolated_user_data(tmp)
        data_dir.mkdir(parents=True)
        old_config = default_config()
        old_config.pop("config_version", None)
        old_config.update({"from_station_cn": "北京", "to_station_cn": "上海", "passengers": "张三"})
        (data_dir / "user_config.json").write_text(json.dumps(old_config, ensure_ascii=False), encoding="utf-8")
        (data_dir / "ui_preferences.json").write_text('{"theme":"dark"}', encoding="utf-8")
        (data_dir / "trip_draft.json").write_text(json.dumps({"schema_version": 1, "revision": 1,
            "saved_at": time.time(), "config": {"from_station_cn": "北京南"}}, ensure_ascii=False), encoding="utf-8")
        journal = OrderJournal(data_dir / "orders.sqlite3")
        old_intent = OrderIntent("regular", "G1", "2026-09-24", "北京", "上海", "二等座", ("张三",))
        with journal.connection() as db:
            db.execute("INSERT INTO orders VALUES(?,?,?,?,?,?,?)", (old_intent.intent_id, "run-old",
                json.dumps(old_intent.__dict__, ensure_ascii=False), "{}",
                json.dumps(OrderResult("fulfilled", order_id="E1", evidence={"matched": True}).payload()), 0, 100.0))
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        env.pop("ELECTRON_RUN_AS_NODE", None)
        options = {}
        if IS_WINDOWS:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            options["startupinfo"] = startup
        log_dir = ROOT / "build" / "qa"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "packaged-smoke.log", "w", encoding="utf-8") as log:
            process = subprocess.Popen([str(EXE), f"--remote-debugging-port={port}", f"--remote-allow-origins=http://localhost:{port}", f"--user-data-dir={tmp}/electron"], env=env, stdout=log, stderr=log, **options)
            ws = None
            try:
                endpoint = None
                for _ in range(100):
                    if process.poll() is not None:
                        raise RuntimeError(f"Electron exited early: {process.returncode}")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/json", timeout=1) as response:
                            tabs = json.load(response)
                        endpoint = next((tab["webSocketDebuggerUrl"] for tab in tabs if tab["type"] == "page"), None)
                        if endpoint: break
                    except OSError: pass
                    time.sleep(0.2)
                if not endpoint: raise RuntimeError("Electron DevTools endpoint did not start")
                ws = websocket.create_connection(endpoint, timeout=30, origin=f"http://localhost:{port}")
                next_id = 0
                def call(method, params=None):
                    nonlocal next_id
                    next_id += 1
                    ws.send(json.dumps({"id":next_id,"method":method,"params":params or {}}))
                    while True:
                        message = json.loads(ws.recv())
                        if message.get("id") == next_id:
                            if "error" in message: raise RuntimeError(message["error"])
                            return message["result"]
                def evaluate(expression):
                    result = call("Runtime.evaluate", {"expression":expression,"awaitPromise":True,"returnByValue":True})
                    if "exceptionDetails" in result: raise RuntimeError(result["exceptionDetails"])
                    return result["result"].get("value")
                for _ in range(100):
                    if evaluate("typeof window.railwatch?.command === 'function' && document.querySelectorAll('.nav .nav-item').length === 6"):
                        break
                    time.sleep(0.2)
                else:
                    raise RuntimeError("Packaged renderer navigation did not become ready")
                assert evaluate("typeof window.railwatch.command") == "function"
                config = evaluate("window.railwatch.command('loadConfig')")
                assert config["auto_submit"] is False and config["auto_alternate"] is False
                assert config["from_station_cn"] == "北京" and config["passengers"] == "张三"
                trip_state = evaluate("window.railwatch.command('loadTripState')")
                assert trip_state["draft"]["status"] == "available" and trip_state["draft"]["draft"]["revision"] == 1
                assert evaluate("window.railwatch.command('loadPreferences').then(p => p.theme)") == "dark"
                history = evaluate("window.railwatch.command('orderHistory', {limit:10})")
                assert len(history["items"]) == 1 and history["items"][0]["official_status"] == "fulfilled"
                detail = evaluate(f"window.railwatch.command('orderDetail', {{intent_id:{json.dumps(old_intent.intent_id)}}})")
                assert detail["history_complete"] is False and detail["summary"]["official_verified_at"] is None
                config.pop("config_version", None)
                saved = evaluate(f"window.railwatch.command('saveConfig', {{config:{json.dumps(config, ensure_ascii=False)}}})")
                assert saved["config_version"] == 2
                runtime = evaluate("window.railwatch.command('getRuntimeInfo')")
                expected_version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
                assert runtime["app_version"] == expected_version
                assert runtime["core_available"] and runtime["date_policy"]["timezone"] == "Asia/Shanghai"
                assert "task" in runtime["state"]
                assert os.path.realpath(runtime["data_dir"]).startswith(tmp), runtime["data_dir"]
                assert evaluate("window.railwatch.command('stopMonitor').then(s => s.monitoring)") is False
                evaluate("[...document.querySelectorAll('.nav-item')].find(b => b.textContent.includes('购票监控')).click()")
                # Initial trip loading can finish after the direct IPC checks.
                for _ in range(50):
                    if evaluate("document.querySelector('.st-btn-start')?.disabled") is False:
                        break
                    time.sleep(0.2)
                image = call("Page.captureScreenshot", {"format":"png"})
                (log_dir / "packaged-monitor.png").write_bytes(base64.b64decode(image["data"]))
                assert evaluate("document.querySelector('.st-btn-start')?.disabled") is False, evaluate("document.querySelector('.page-surface')?.innerText")
                print(json.dumps({"preload":True,"runtime":True,"legacy_config":True,"draft":True,
                    "legacy_order":True,"valid_start_without_results":True,"stop":True,
                    "screenshot":str(log_dir / "packaged-monitor.png")}, ensure_ascii=False))
                try: call("Browser.close")
                except (websocket.WebSocketException, OSError): pass
                process.wait(timeout=15)
            finally:
                if ws: ws.close()
                stop(process)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--exe":
        EXE = Path(sys.argv[2]).resolve()
    elif not IS_WINDOWS:
        raise SystemExit("Pass --exe with the packaged app executable on this platform.")
    if not EXE.is_file():
        raise SystemExit(f"Packaged app not found: {EXE}")
    main()
