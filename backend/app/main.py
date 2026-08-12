from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .discovery import DiscoveryError, inspect_project
from .metrics import numeric_metrics, parse_metrics
from .preflight import preflight_project
from .process_manager import manager


app = FastAPI(title="通用深度学习训练管理器", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PathBody(BaseModel):
    path: str


class ProjectBody(BaseModel):
    inspection: dict[str, Any]


class ExperimentBody(BaseModel):
    project_id: int
    name: str = Field(min_length=1, max_length=100)
    values: dict[str, Any] = Field(default_factory=dict)


class ControlBody(BaseModel):
    values: dict[str, Any]


class PreflightBody(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@app.on_event("startup")
def startup() -> None:
    db.init_db()
    db.execute("UPDATE jobs SET status=?,finished_at=?,error_message=? WHERE status IN ('RUNNING','STARTING','STOPPING')", ("INTERRUPTED", db.now(), "管理服务重启，无法恢复原进程连接"))
    db.execute("UPDATE experiments SET status=? WHERE status IN ('RUNNING','STARTING','STOPPING')", ("INTERRUPTED",))


@app.on_event("shutdown")
async def shutdown() -> None:
    await manager.shutdown()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.post("/api/system/select-directory")
async def select_directory() -> dict[str, str]:
    def show() -> str:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            return filedialog.askdirectory(title="选择深度学习项目文件夹", mustexist=True)
        finally:
            root.destroy()
    try:
        return {"path": await asyncio.to_thread(show)}
    except Exception as exc:
        raise HTTPException(500, f"无法打开系统文件夹选择窗口：{exc}") from exc


@app.post("/api/projects/inspect")
def inspect(body: PathBody) -> dict[str, Any]:
    try:
        return inspect_project(body.path)
    except DiscoveryError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/projects")
def create_project(body: ProjectBody) -> dict[str, Any]:
    item = body.inspection
    try:
        project_id = db.execute(
            "INSERT INTO projects(name,path,framework,entrypoint,adapter_json,created_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET name=excluded.name,framework=excluded.framework,entrypoint=excluded.entrypoint,adapter_json=excluded.adapter_json",
            (item["name"], item["path"], item["framework"], item["entrypoint"], json.dumps(item["adapter"], ensure_ascii=False), db.now()),
        )
        row = db.query_one("SELECT * FROM projects WHERE path=?", (item["path"],))
        return db.decode(row, "adapter_json") or {"id": project_id}
    except (KeyError, TypeError) as exc:
        raise HTTPException(400, f"项目检查结果不完整：{exc}") from exc


@app.get("/api/projects")
def projects() -> list[dict[str, Any]]:
    return [db.decode(row, "adapter_json") for row in db.query("SELECT * FROM projects ORDER BY id DESC")]


@app.get("/api/projects/{project_id}")
def project(project_id: int) -> dict[str, Any]:
    item = db.decode(db.query_one("SELECT * FROM projects WHERE id=?", (project_id,)), "adapter_json")
    if not item:
        raise HTTPException(404, "项目不存在")
    return item


@app.post("/api/projects/{project_id}/preflight")
def preflight(project_id: int, body: PreflightBody) -> dict[str, Any]:
    item = db.decode(db.query_one("SELECT * FROM projects WHERE id=?", (project_id,)), "adapter_json")
    if not item:
        raise HTTPException(404, "项目不存在")
    return preflight_project(item, body.values)


@app.post("/api/experiments")
def create_experiment(body: ExperimentBody) -> dict[str, Any]:
    if not db.query_one("SELECT id FROM projects WHERE id=?", (body.project_id,)):
        raise HTTPException(404, "项目不存在")
    experiment_id = db.execute(
        "INSERT INTO experiments(project_id,name,values_json,status,created_at) VALUES(?,?,?,?,?)",
        (body.project_id, body.name, json.dumps(body.values, ensure_ascii=False), "CREATED", db.now()),
    )
    return db.decode(db.query_one("SELECT * FROM experiments WHERE id=?", (experiment_id,)), "values_json") or {}


@app.get("/api/experiments")
def experiments() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT e.*,p.name project_name FROM experiments e JOIN projects p ON p.id=e.project_id ORDER BY e.id DESC"
    )
    return [db.decode(row, "values_json") for row in rows]


@app.post("/api/experiments/{experiment_id}/start")
async def start_experiment(experiment_id: int) -> dict[str, Any]:
    experiment = db.decode(db.query_one("SELECT * FROM experiments WHERE id=?", (experiment_id,)), "values_json")
    if not experiment:
        raise HTTPException(404, "实验不存在")
    if experiment["status"] in {"RUNNING", "STARTING"}:
        raise HTTPException(409, "实验已经在运行")
    project_item = db.decode(db.query_one("SELECT * FROM projects WHERE id=?", (experiment["project_id"],)), "adapter_json")
    check = await asyncio.to_thread(preflight_project, project_item, experiment["values"])  # type: ignore[arg-type]
    errors = [item["message"] for item in check["issues"] if item["level"] == "error"]
    if errors:
        raise HTTPException(400, "启动前检查未通过：" + "；".join(errors))
    if check["changes"]:
        raise HTTPException(400, "检测到可修正的路径参数，请在页面完成启动前检查并确认修正")
    try:
        return await manager.start(project_item, experiment)  # type: ignore[arg-type]
    except Exception as exc:
        raise HTTPException(500, f"训练启动失败：{exc}") from exc


@app.get("/api/jobs")
def jobs() -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT j.*,e.name experiment_name,p.name project_name FROM jobs j "
        "JOIN experiments e ON e.id=j.experiment_id JOIN projects p ON p.id=e.project_id ORDER BY j.id DESC"
    )
    return [db.decode(row, "command_json") for row in rows]


@app.get("/api/jobs/{job_id}")
def job(job_id: int) -> dict[str, Any]:
    item = db.decode(db.query_one("SELECT * FROM jobs WHERE id=?", (job_id,)), "command_json")
    if not item:
        raise HTTPException(404, "任务不存在")
    return item


@app.post("/api/jobs/{job_id}/stop")
async def stop_job(job_id: int) -> dict[str, bool]:
    if not await manager.stop(job_id):
        raise HTTPException(409, "任务未运行或已经结束")
    return {"stopping": True}


@app.patch("/api/jobs/{job_id}/control")
async def update_control(job_id: int, body: ControlBody) -> dict[str, Any]:
    try:
        return await manager.update_control(job_id, body.values)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.get("/api/jobs/{job_id}/logs")
def logs(job_id: int, limit: int = 500) -> dict[str, Any]:
    job_item = db.query_one("SELECT run_dir FROM jobs WHERE id=?", (job_id,))
    if not job_item:
        raise HTTPException(404, "任务不存在")
    path = Path(job_item["run_dir"]) / "training.log"
    if path.is_file():
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-min(limit, 5000):]
    else:
        lines = list(manager.logs[job_id])[-limit:]
    return {"lines": lines}


@app.get("/api/jobs/{job_id}/metrics")
def metrics(job_id: int) -> list[dict[str, Any]]:
    rows = db.query("SELECT name,value,epoch,step,recorded_at FROM metrics WHERE job_id=? ORDER BY id", (job_id,))
    if rows:
        return rows
    job_item = db.query_one("SELECT run_dir,finished_at,started_at FROM jobs WHERE id=?", (job_id,))
    if not job_item:
        raise HTTPException(404, "任务不存在")
    path = Path(job_item["run_dir"]) / "training.log"
    if not path.is_file():
        return []
    recorded_at = job_item.get("finished_at") or job_item.get("started_at") or db.now()
    with path.open("r", encoding="utf-8", errors="replace") as log_file:
        for line in log_file:
            payload = parse_metrics(line)
            if not payload:
                continue
            epoch, step, values = numeric_metrics(payload)
            for name, value in values.items():
                db.execute(
                    "INSERT INTO metrics(job_id,name,value,epoch,step,recorded_at) VALUES(?,?,?,?,?,?)",
                    (job_id, name, value, epoch, step, recorded_at),
                )
    return db.query("SELECT name,value,epoch,step,recorded_at FROM metrics WHERE job_id=? ORDER BY id", (job_id,))


@app.websocket("/api/ws/jobs/{job_id}")
async def job_socket(websocket: WebSocket, job_id: int) -> None:
    await websocket.accept()
    manager.listeners[job_id].add(websocket)
    try:
        await websocket.send_json({"type": "connected", "job_id": job_id})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.listeners[job_id].discard(websocket)


FRONTEND = db.ROOT / "frontend" / "dist"
if FRONTEND.is_dir():
    assets = FRONTEND / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        candidate = (FRONTEND / path).resolve()
        if candidate.is_file() and FRONTEND in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(FRONTEND / "index.html")
