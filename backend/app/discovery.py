from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


ADAPTER_FILE = ".dl-manager.json"
ENTRYPOINT_NAMES = ("train.py", "main.py", "run.py", "trainer.py")
COMMON_NAMES = {
    "epochs", "epoch", "batch_size", "learning_rate", "lr", "weight_decay",
    "num_workers", "seed", "dropout", "momentum", "device", "optimizer",
    "model", "data_dir", "dataset", "save_dir", "output_dir", "patience",
    "gradient_accumulation_steps", "warmup_epochs", "max_steps",
}


class DiscoveryError(ValueError):
    pass


def literal(node: ast.AST | None) -> Any:
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        if isinstance(node, ast.Name):
            return node.id
        return None


def value_type(value: Any, explicit: str | None = None) -> str:
    if explicit in {"int", "float", "str", "bool"}:
        return {"int": "integer", "float": "number", "str": "string", "bool": "boolean"}[explicit]
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, list):
        return "array"
    return "string"


def parse_argparse(script: Path) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(script.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    parameters: list[dict[str, Any]] = []
    known: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        flags = [literal(arg) for arg in node.args]
        flags = [flag for flag in flags if isinstance(flag, str)]
        if not flags:
            continue
        options = {kw.arg: literal(kw.value) for kw in node.keywords if kw.arg}
        flag = next((item for item in flags if item.startswith("--")), flags[0])
        key = options.get("dest") or flag.lstrip("-").replace("-", "_")
        if key in known or key in {"help"}:
            continue
        action = options.get("action")
        default = options.get("default")
        if action == "store_true" and default is None:
            default = False
        if action == "store_false" and default is None:
            default = True
        explicit_type = options.get("type") if isinstance(options.get("type"), str) else None
        parameters.append({
            "key": key,
            "label": key.replace("_", " ").title(),
            "flag": flag,
            "type": value_type(default, explicit_type),
            "default": default,
            "required": bool(options.get("required", False)),
            "choices": options.get("choices"),
            "help": options.get("help") or "从训练入口的 argparse 自动识别",
            "action": action,
            "runtime_editable": key in {"learning_rate", "lr", "epochs", "max_epochs"},
        })
        known.add(key)
    return parameters


def parse_common_assignments(script: Path, known: set[str]) -> list[dict[str, Any]]:
    try:
        tree = ast.parse(script.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return []
    found: list[dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        raw_value = node.value
        for target in targets:
            if not isinstance(target, ast.Name) or target.id not in COMMON_NAMES or target.id in known:
                continue
            default = literal(raw_value)
            if isinstance(default, (str, int, float, bool)):
                found.append({
                    "key": target.id,
                    "label": target.id.replace("_", " ").title(),
                    "flag": None,
                    "type": value_type(default),
                    "default": default,
                    "required": False,
                    "choices": None,
                    "help": "发现了源码常量；通用模式不会直接修改源码，请创建适配文件后启用此参数",
                    "action": None,
                    "runtime_editable": False,
                    "read_only": True,
                })
                known.add(target.id)
    return found


def flatten_config(value: Any, prefix: str = "") -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(value, dict):
        return result
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            result.extend(flatten_config(item, path))
        elif isinstance(item, (str, int, float, bool)) or item is None:
            result.append({
                "key": path,
                "label": path.replace("_", " "),
                "flag": None,
                "type": value_type(item),
                "default": item,
                "required": False,
                "choices": None,
                "help": "从项目配置文件读取",
                "action": None,
                "runtime_editable": path.split(".")[-1] in {"learning_rate", "lr", "epochs", "max_epochs"},
                "config_key": path,
            })
    return result


def find_config(root: Path) -> tuple[Path | None, list[dict[str, Any]]]:
    names = ("config.yaml", "config.yml", "config.json", "config.default.yaml", "config.default.yml")
    for name in names:
        path = root / name
        if not path.is_file():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8")) if path.suffix == ".json" else yaml.safe_load(path.read_text(encoding="utf-8"))
            return path, flatten_config(raw)
        except Exception:
            continue
    return None, []


def detect_framework(root: Path, entrypoint: Path) -> str:
    evidence = ""
    for name in ("requirements.txt", "pyproject.toml", "environment.yml"):
        path = root / name
        if path.is_file():
            evidence += path.read_text(encoding="utf-8", errors="ignore").lower()
    evidence += entrypoint.read_text(encoding="utf-8", errors="ignore").lower()
    checks = (
        ("ultralytics", "Ultralytics"), ("pytorch_lightning", "PyTorch Lightning"),
        ("lightning", "PyTorch Lightning"), ("transformers", "Hugging Face"),
        ("tensorflow", "TensorFlow"), ("keras", "Keras"), ("torch", "PyTorch"),
        ("jax", "JAX"),
    )
    return next((label for token, label in checks if token in evidence), "Python")


def normalize_adapter(raw: dict[str, Any], root: Path) -> dict[str, Any]:
    entrypoint = raw.get("entrypoint", "train.py")
    if isinstance(entrypoint, dict):
        entrypoint = entrypoint.get("script", "train.py")
    entry = (root / entrypoint).resolve()
    if not entry.is_file() or root not in entry.parents:
        raise DiscoveryError("适配文件中的训练入口不存在或超出项目目录")
    params = raw.get("parameters", [])
    if isinstance(params, dict):
        params = [{"key": key, **value} for key, value in params.items()]
    for param in params:
        param.setdefault("label", param["key"].replace("_", " ").title())
        param.setdefault("type", value_type(param.get("default")))
        param.setdefault("required", False)
        param.setdefault("runtime_editable", False)
    return {
        "version": raw.get("version", 1),
        "mode": "explicit",
        "framework": raw.get("framework", "Python"),
        "entrypoint": str(entry.relative_to(root)),
        "python": raw.get("python", sys.executable),
        "arguments": raw.get("arguments", []),
        "parameters": params,
        "metric_prefix": raw.get("metric_prefix", "@@METRIC@@"),
        "config_format": raw.get("config_format", "json"),
    }


def inspect_project(path: str) -> dict[str, Any]:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise DiscoveryError("所选路径不是有效文件夹")
    explicit = root / ADAPTER_FILE
    if explicit.is_file():
        try:
            adapter = normalize_adapter(json.loads(explicit.read_text(encoding="utf-8")), root)
        except json.JSONDecodeError as exc:
            raise DiscoveryError(f"{ADAPTER_FILE} 格式错误：{exc}") from exc
    else:
        entry = next((root / name for name in ENTRYPOINT_NAMES if (root / name).is_file()), None)
        if not entry:
            candidates = sorted(root.glob("*train*.py"))
            entry = candidates[0] if candidates else None
        if not entry:
            raise DiscoveryError("没有找到 train.py、main.py 或其他训练入口，请添加 .dl-manager.json")
        cli_params = parse_argparse(entry)
        known = {item["key"] for item in cli_params}
        config_path, config_params = find_config(root)
        parameters = cli_params
        config_flag = next((item for item in cli_params if item["key"] in {"config", "config_path", "cfg"}), None)
        if config_path and config_flag:
            existing = {item["key"] for item in parameters}
            parameters += [item for item in config_params if item["key"] not in existing]
        parameters += parse_common_assignments(entry, {item["key"] for item in parameters})
        adapter = {
            "version": 1,
            "mode": "automatic",
            "framework": detect_framework(root, entry),
            "entrypoint": str(entry.relative_to(root)),
            "python": sys.executable,
            "arguments": [],
            "parameters": parameters,
            "metric_prefix": "@@METRIC@@",
            "config_path": str(config_path.relative_to(root)) if config_path else None,
            "config_flag": config_flag["flag"] if config_flag else None,
            "config_format": config_path.suffix.lstrip(".") if config_path else "json",
        }
    warnings: list[str] = []
    if adapter["mode"] == "automatic":
        warnings.append("自动识别不会执行或修改项目源码；复杂参数请使用 .dl-manager.json 精确描述。")
    if not adapter["parameters"]:
        warnings.append("没有发现可调参数，但仍可使用默认命令启动。")
    return {
        "name": root.name,
        "path": str(root),
        "framework": adapter["framework"],
        "entrypoint": adapter["entrypoint"],
        "adapter": adapter,
        "warnings": warnings,
    }

