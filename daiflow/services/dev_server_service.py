"""Dev server lifecycle manager.

Manages dev server subprocesses for task preview. Each task has at most
one running dev server (the first repo with a configured dev_command).
"""

import asyncio
import logging
import socket
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_PORT_READY_TIMEOUT = 30
_STOP_TIMEOUT = 5


@dataclass
class DevServerProcess:
    proc: asyncio.subprocess.Process
    task_id: str
    repo_id: str
    port: int
    cwd: str
    preview_url: str = ""


def build_preview_url(
    task_id: str, port: int, preview_url: str, server_host: str = "",
) -> str:
    """Build the URL the user should open to preview the dev server.

    - mode=builtin → /api/dev-preview/{task_id}/  (relative, works anywhere)
    - mode=local   → http://localhost:{port} or preview_url if set
    """
    from daiflow.config import PREVIEW_MODE

    if PREVIEW_MODE == "builtin":
        path_suffix = ""
        if preview_url:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(preview_url)
                p = parsed.path
                if p and p != "/":
                    path_suffix = p.lstrip("/")
            except Exception:
                pass

        host = server_host or "localhost:8000"
        scheme = "https" if "443" in host else "http"
        return f"{scheme}://{host}/api/dev-preview/{task_id}/{path_suffix}"

    if preview_url:
        return preview_url
    return f"http://localhost:{port}"


class DevServerManager:
    """Singleton that tracks dev server subprocesses keyed by task_id."""

    def __init__(self):
        self._processes: dict[str, DevServerProcess] = {}

    async def start(
        self, task_id: str, repo_id: str, command: str, port: int, cwd: str,
        preview_url: str = "", server_host: str = "",
    ) -> dict:
        if task_id in self._processes:
            entry = self._processes[task_id]
            if entry.proc.returncode is None:
                url = build_preview_url(task_id, entry.port, entry.preview_url, server_host)
                return {
                    "running": True,
                    "url": url,
                    "port": entry.port,
                    "preview_url": entry.preview_url,
                }
            del self._processes[task_id]

        if _is_port_in_use(port):
            raise RuntimeError(f"Port {port} is already in use")

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=cwd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )

        self._processes[task_id] = DevServerProcess(
            proc=proc, task_id=task_id, repo_id=repo_id, port=port, cwd=cwd,
            preview_url=preview_url,
        )

        try:
            await _wait_for_port(port, timeout=_PORT_READY_TIMEOUT)
        except TimeoutError:
            await self.stop(task_id)
            raise RuntimeError(
                f"Dev server did not become ready on port {port} within {_PORT_READY_TIMEOUT}s"
            )

        logger.info("Dev server started for task %s on port %d (pid=%d)", task_id, port, proc.pid)
        url = build_preview_url(task_id, port, preview_url, server_host)
        return {"running": True, "url": url, "port": port, "preview_url": preview_url}

    async def stop(self, task_id: str) -> None:
        entry = self._processes.pop(task_id, None)
        if entry is None:
            return
        await _terminate(entry.proc)
        logger.info("Dev server stopped for task %s", task_id)

    def status(self, task_id: str, server_host: str = "") -> dict:
        entry = self._processes.get(task_id)
        if entry is None or entry.proc.returncode is not None:
            if entry and entry.proc.returncode is not None:
                self._processes.pop(task_id, None)
            return {"running": False, "url": "", "port": 0, "preview_url": ""}
        url = build_preview_url(task_id, entry.port, entry.preview_url, server_host)
        return {
            "running": True,
            "url": url,
            "port": entry.port,
            "preview_url": entry.preview_url,
        }

    async def stop_all(self) -> None:
        tasks = [self.stop(tid) for tid in list(self._processes)]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("All dev servers stopped")


dev_server_manager = DevServerManager()


def _is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


async def _wait_for_port(port: int, timeout: float = 30) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if _is_port_in_use(port):
            return
        await asyncio.sleep(0.5)
    raise TimeoutError(f"Port {port} not ready within {timeout}s")


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=_STOP_TIMEOUT)
    except (asyncio.TimeoutError, ProcessLookupError):
        try:
            proc.kill()
            await proc.wait()
        except Exception:
            pass
