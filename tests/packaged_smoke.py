"""Smoke the packaged Electron/preload/runtime contract using temporary user data."""
import base64
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.request import urlopen
import websocket

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "release" / "win-unpacked" / "RailWatch 12306.exe"


def main():
    with tempfile.TemporaryDirectory(prefix="railwatch-package-test-") as tmp:
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        env = dict(os.environ, LOCALAPPDATA=tmp, APPDATA=tmp, NODE_OPTIONS="")
        env.pop("ELECTRON_RUN_AS_NODE", None)
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        log_dir = ROOT / "build" / "qa"
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "packaged-smoke.log", "w", encoding="utf-8") as log:
            process = subprocess.Popen([str(EXE), f"--remote-debugging-port={port}", f"--remote-allow-origins=http://localhost:{port}", f"--user-data-dir={tmp}/electron"], env=env, stdout=log, stderr=log, startupinfo=startup)
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
                    if evaluate("typeof window.railwatch?.command === 'function' && document.querySelectorAll('.nav-item').length === 4"):
                        break
                    time.sleep(0.2)
                assert evaluate("typeof window.railwatch.command") == "function"
                config = evaluate("window.railwatch.command('loadConfig')")
                assert config["auto_submit"] is False and config["auto_alternate"] is False
                config.pop("config_version", None)
                saved = evaluate(f"window.railwatch.command('saveConfig', {{config:{json.dumps(config, ensure_ascii=False)}}})")
                assert saved["config_version"] == 1
                runtime = evaluate("window.railwatch.command('getRuntimeInfo')")
                assert runtime["core_available"] and runtime["date_policy"]["timezone"] == "Asia/Shanghai"
                assert "task" in runtime["state"]
                assert runtime["data_dir"].startswith(tmp)
                assert evaluate("window.railwatch.command('stopMonitor').then(s => s.monitoring)") is False
                evaluate("[...document.querySelectorAll('.nav-item')].find(b => b.textContent.includes('购票监控')).click()")
                time.sleep(0.4)
                assert evaluate("document.querySelector('.st-btn-start')?.disabled") is False
                image = call("Page.captureScreenshot", {"format":"png"})
                (log_dir / "packaged-monitor.png").write_bytes(base64.b64decode(image["data"]))
                print(json.dumps({"preload":True,"runtime":True,"legacy_config":True,"valid_start_without_results":True,"stop":True,"screenshot":str(log_dir / "packaged-monitor.png")}, ensure_ascii=False))
                try: call("Browser.close")
                except (websocket.WebSocketException, OSError): pass
                process.wait(timeout=15)
            finally:
                if ws: ws.close()
                if process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
