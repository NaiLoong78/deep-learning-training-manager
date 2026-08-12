from __future__ import annotations

import multiprocessing
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = BASE_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until_ready(url: str, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as exc:
            last_error = exc
            time.sleep(0.15)
    raise RuntimeError(f"本地服务启动超时：{last_error}")


class DesktopApi:
    def select_directory(self) -> str:
        import webview

        if not webview.windows:
            return ""
        result: Any = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG, allow_multiple=False)
        if not result:
            return ""
        if isinstance(result, (tuple, list)):
            return str(result[0]) if result else ""
        return str(result)


def run() -> int:
    import uvicorn
    import webview
    from app.main import app

    port = available_port()
    url = f"http://127.0.0.1:{port}"
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None
    server_thread = threading.Thread(target=server.run, name="fastapi-server", daemon=True)
    server_thread.start()

    try:
        wait_until_ready(url)
        webview.create_window(
            "深度学习训练管理器",
            url=url,
            js_api=DesktopApi(),
            width=1360,
            height=860,
            min_size=(980, 680),
            confirm_close=False,
            background_color="#f4f5f7",
        )
        webview.start(debug=False)
        return 0
    finally:
        server.should_exit = True
        server_thread.join(timeout=12)


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(run())
