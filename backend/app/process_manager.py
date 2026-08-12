from __future__ import annotations

import asyncio
import json
import locale
import os
import signal
import sys
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, AsyncIterator

import yaml
from fastapi import WebSocket

from . import db
from .metrics import numeric_metrics, parse_metrics


def decode_output(raw: bytes) -> str:
    """Decode training output from UTF-8 and common Chinese Windows consoles."""
    encodings = ("utf-8", locale.getpreferredencoding(False), "gb18030")
    attempted: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower().replace("-", "")
        if normalized in attempted:
            continue
        attempted.add(normalized)
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def split_output_records(buffer: bytes) -> tuple[list[bytes], bytes]:
    """Split normal lines and carriage-return progress updates without readline limits."""
    records: list[bytes] = []
    while buffer:
        newline = buffer.find(b"\n")
        carriage = buffer.find(b"\r")
        positions = [position for position in (newline, carriage) if position >= 0]
        if not positions:
            # Protect the manager from a program that writes an unbounded line.
            if len(buffer) > 1024 * 1024:
                records.append(buffer[:1024 * 1024])
                buffer = buffer[1024 * 1024:]
                continue
            break
        position = min(positions)
        record = buffer[:position]
        separator_size = 2 if buffer[position:position + 2] == b"\r\n" else 1
        buffer = buffer[position + separator_size:]
        if record:
            records.append(record)
    return records, buffer


async def iter_output_records(stream: asyncio.StreamReader) -> AsyncIterator[bytes]:
    """Read stdout in chunks so tqdm's carriage returns cannot exceed StreamReader limits."""
    buffer = b""
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            break
        records, buffer = split_output_records(buffer + chunk)
        for record in records:
            yield record
    if buffer:
        yield buffer


def nested_set(target: dict[str, Any], dotted: str, value: Any) -> None:
    cursor = target
    parts = dotted.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value


class ProcessManager:
    def __init__(self) -> None:
        self.processes: dict[int, asyncio.subprocess.Process] = {}
        self.listeners: dict[int, set[WebSocket]] = defaultdict(set)
        self.logs: dict[int, deque[str]] = defaultdict(lambda: deque(maxlen=1000))

    def build_command(self, project: dict[str, Any], experiment: dict[str, Any], run_dir: Path) -> tuple[list[str], Path]:
        adapter = project["adapter"]
        values = experiment["values"]
        python = adapter.get("python") or sys.executable
        command = [python, str(Path(project["path"]) / adapter["entrypoint"])]
        config_values: dict[str, Any] = {}
        parameter_map = {item["key"]: item for item in adapter.get("parameters", [])}
        for key, value in values.items():
            parameter = parameter_map.get(key, {})
            if parameter.get("config_key"):
                nested_set(config_values, parameter["config_key"], value)
        config_path = run_dir / "experiment_config.yaml"
        if config_values:
            config_path.write_text(yaml.safe_dump(config_values, allow_unicode=True, sort_keys=False), encoding="utf-8")
        if adapter.get("mode") == "explicit":
            replacements = {
                "{config_path}": str(config_path), "{run_dir}": str(run_dir),
                "{project_path}": project["path"],
            }
            for argument in adapter.get("arguments", []):
                text = str(argument)
                for token, replacement in replacements.items():
                    text = text.replace(token, replacement)
                for key, value in values.items():
                    text = text.replace("{" + key + "}", str(value))
                command.append(text)
            explicitly_used = " ".join(map(str, adapter.get("arguments", [])))
            for key, value in values.items():
                parameter = parameter_map.get(key, {})
                flag = parameter.get("flag")
                if not flag or "{" + key + "}" in explicitly_used:
                    continue
                self._append_flag(command, flag, value, parameter.get("action"))
        else:
            if config_values and adapter.get("config_flag"):
                command += [adapter["config_flag"], str(config_path)]
            for key, value in values.items():
                parameter = parameter_map.get(key, {})
                flag = parameter.get("flag")
                if not flag or parameter.get("read_only") or parameter.get("config_key"):
                    continue
                self._append_flag(command, flag, value, parameter.get("action"))
        return command, config_path

    @staticmethod
    def _append_flag(command: list[str], flag: str, value: Any, action: str | None) -> None:
        if action == "store_true":
            if value:
                command.append(flag)
        elif action == "store_false":
            if value is False:
                command.append(flag)
        elif value is not None and value != "":
            if isinstance(value, list):
                command.extend([flag, *map(str, value)])
            else:
                command.extend([flag, str(value)])

    async def start(self, project: dict[str, Any], experiment: dict[str, Any]) -> dict[str, Any]:
        provisional = db.execute(
            "INSERT INTO jobs(experiment_id,status,command_json,run_dir) VALUES(?,?,?,?)",
            (experiment["id"], "STARTING", "[]", ""),
        )
        run_dir = db.RUNS_DIR / f"experiment-{experiment['id']}-job-{provisional}"
        run_dir.mkdir(parents=True, exist_ok=True)
        command, _ = self.build_command(project, experiment, run_dir)
        control_path = run_dir / "control.json"
        control_path.write_text(json.dumps({"version": 1, "stop_requested": False}, ensure_ascii=False, indent=2), encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "DL_MANAGER_RUN_DIR": str(run_dir),
            "DL_MANAGER_CONTROL_FILE": str(control_path),
        })
        flags = getattr(asyncio.subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=project["path"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
        except Exception as exc:
            db.execute("UPDATE jobs SET status=?,error_message=?,finished_at=? WHERE id=?", ("FAILED", str(exc), db.now(), provisional))
            db.execute("UPDATE experiments SET status=? WHERE id=?", ("FAILED", experiment["id"]))
            raise
        self.processes[provisional] = process
        db.execute(
            "UPDATE jobs SET pid=?,status=?,command_json=?,run_dir=?,started_at=? WHERE id=?",
            (process.pid, "RUNNING", json.dumps(command, ensure_ascii=False), str(run_dir), db.now(), provisional),
        )
        db.execute("UPDATE experiments SET status=? WHERE id=?", ("RUNNING", experiment["id"]))
        asyncio.create_task(self._read(provisional, experiment["id"], process, project["adapter"].get("metric_prefix", "@@METRIC@@"), run_dir))
        return db.decode(db.query_one("SELECT * FROM jobs WHERE id=?", (provisional,)), "command_json") or {}

    async def _read(self, job_id: int, experiment_id: int, process: asyncio.subprocess.Process, prefix: str, run_dir: Path) -> None:
        log_path = run_dir / "training.log"
        try:
            assert process.stdout
            with log_path.open("a", encoding="utf-8") as log_file:
                async for raw in iter_output_records(process.stdout):
                    line = decode_output(raw).rstrip()
                    log_file.write(line + "\n")
                    log_file.flush()
                    self.logs[job_id].append(line)
                    await self.broadcast(job_id, {"type": "log", "line": line})
                    payload = parse_metrics(line, prefix)
                    if payload:
                        epoch, step, metrics = numeric_metrics(payload)
                        for name, value in metrics.items():
                            db.execute(
                                "INSERT INTO metrics(job_id,name,value,epoch,step,recorded_at) VALUES(?,?,?,?,?,?)",
                                (job_id, name, value, epoch, step, db.now()),
                            )
                        await self.broadcast(job_id, {"type": "metric", "data": payload})
            return_code = await process.wait()
            current = db.query_one("SELECT status FROM jobs WHERE id=?", (job_id,)) or {}
            status = "STOPPED" if current.get("status") == "STOPPING" else ("COMPLETED" if return_code == 0 else "FAILED")
            db.execute("UPDATE jobs SET status=?,exit_code=?,finished_at=? WHERE id=?", (status, return_code, db.now(), job_id))
            db.execute("UPDATE experiments SET status=? WHERE id=?", (status, experiment_id))
            await self.broadcast(job_id, {"type": "status", "status": status, "exit_code": return_code})
        except Exception as exc:
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            db.execute("UPDATE jobs SET status=?,error_message=?,finished_at=? WHERE id=?", ("FAILED", str(exc), db.now(), job_id))
            db.execute("UPDATE experiments SET status=? WHERE id=?", ("FAILED", experiment_id))
            await self.broadcast(job_id, {"type": "status", "status": "FAILED", "error": str(exc)})
        finally:
            self.processes.pop(job_id, None)

    async def stop(self, job_id: int) -> bool:
        job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        process = self.processes.get(job_id)
        if not job or not process or process.returncode is not None:
            return False
        db.execute("UPDATE jobs SET status=? WHERE id=?", ("STOPPING", job_id))
        control_path = Path(job["run_dir"]) / "control.json"
        control = {"version": 1, "stop_requested": True}
        control_path.write_text(json.dumps(control, ensure_ascii=False, indent=2), encoding="utf-8")
        await self.broadcast(job_id, {"type": "status", "status": "STOPPING"})
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        return True

    async def shutdown(self) -> None:
        job_ids = [job_id for job_id, process in self.processes.items() if process.returncode is None]
        if job_ids:
            await asyncio.gather(*(self.stop(job_id) for job_id in job_ids), return_exceptions=True)

    async def update_control(self, job_id: int, values: dict[str, Any]) -> dict[str, Any]:
        job = db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,))
        if not job or job["status"] not in {"RUNNING", "STARTING"}:
            raise ValueError("任务当前不可控制")
        path = Path(job["run_dir"]) / "control.json"
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1}
        current.update(values)
        current["version"] = int(current.get("version", 0)) + 1
        path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        await self.broadcast(job_id, {"type": "control", "data": current})
        return current

    async def broadcast(self, job_id: int, message: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for socket in self.listeners[job_id]:
            try:
                await socket.send_json(message)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.listeners[job_id].discard(socket)


manager = ProcessManager()
