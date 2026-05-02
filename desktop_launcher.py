from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8788
PID_FILE = ROOT / "logs" / "desktop_server.pid"


def build_url(host: str, port: int, path: str = "/overlay") -> str:
    clean_path = path if path.startswith("/") else f"/{path}"
    return f"http://{host}:{port}{clean_path}"


def is_alive(url: str, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def start_server(host: str, port: int) -> subprocess.Popen[str] | None:
    health_url = build_url(host, port, "/api/health")
    if is_alive(health_url):
        return None

    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["CUSTOMER_ASSISTANT_HOST"] = host
    env["CUSTOMER_ASSISTANT_PORT"] = str(port)
    log_path = ROOT / "logs" / "desktop_server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py")],
        cwd=str(ROOT),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")

    for _ in range(30):
        if is_alive(health_url):
            return process
        if process.poll() is not None:
            raise RuntimeError(f"服务启动失败，请查看日志：{log_path}")
        time.sleep(0.25)
    raise TimeoutError(f"服务启动超时，请查看日志：{log_path}")


def chrome_app_command(url: str) -> list[str] | None:
    chrome_path = Path("/Applications/Google Chrome.app")
    if not chrome_path.exists():
        return None
    return [
        "open",
        "-na",
        "Google Chrome",
        "--args",
        f"--app={url}",
        "--window-size=430,720",
        "--window-position=980,80",
    ]


def browser_command(url: str) -> list[str]:
    return chrome_app_command(url) or ["open", url]


def open_overlay(host: str, port: int) -> None:
    url = build_url(host, port, "/overlay")
    subprocess.run(browser_command(url), check=True)


def stop_server() -> bool:
    if not PID_FILE.exists():
        return False
    raw = PID_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return False
    try:
        os.kill(int(raw), 15)
    except ProcessLookupError:
        pass
    PID_FILE.unlink(missing_ok=True)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="启动门窗售前悬浮提示小窗")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--stop", action="store_true", help="停止由桌面启动器拉起的本地服务")
    args = parser.parse_args()

    if args.stop:
        stopped = stop_server()
        print("已停止本地服务" if stopped else "没有找到桌面启动器服务")
        return

    start_server(args.host, args.port)
    open_overlay(args.host, args.port)
    print(f"已打开门窗售前提示：{build_url(args.host, args.port, '/overlay')}")


if __name__ == "__main__":
    main()
