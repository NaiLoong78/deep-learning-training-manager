from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
DATA_PATH_KEYS = {
    "data_dir", "dataset_dir", "data_path", "dataset_path", "data_root",
    "dataset_root", "image_dir", "images_dir", "train_dir", "val_dir", "test_dir",
}
OUTPUT_PATH_KEYS = {"output_dir", "save_dir", "run_dir", "log_dir", "checkpoint_dir"}
FRAMEWORK_IMPORTS: dict[str, tuple[str, ...]] = {
    "pytorch": ("torch",),
    "pytorch lightning": ("lightning", "pytorch_lightning"),
    "tensorflow": ("tensorflow",),
    "keras": ("keras",),
    "hugging face": ("transformers",),
    "ultralytics": ("ultralytics",),
    "jax": ("jax",),
}


def _issue(
    level: str,
    code: str,
    message: str,
    *,
    parameter: str | None = None,
    original: Any = None,
    suggested: Any = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"level": level, "code": code, "message": message}
    if parameter is not None:
        result["parameter"] = parameter
    if original is not None:
        result["original"] = original
    if suggested is not None:
        result["suggested"] = suggested
    return result


def _resolve_python(raw: Any, root: Path) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    expanded = os.path.expandvars(os.path.expanduser(text))
    candidate = Path(expanded)
    if candidate.is_absolute() or candidate.parent != Path("."):
        if not candidate.is_absolute():
            candidate = root / candidate
        return str(candidate.resolve()) if candidate.is_file() else None
    return shutil.which(expanded)


def _run_python(python: str, arguments: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [python, *arguments],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _visible_directories(path: Path) -> list[Path]:
    try:
        return [item for item in path.iterdir() if item.is_dir() and not item.name.startswith(".")]
    except OSError:
        return []


def _has_direct_image(path: Path) -> bool:
    try:
        return any(item.is_file() and item.suffix.lower() in IMAGE_EXTENSIONS for item in path.iterdir())
    except OSError:
        return False


def _looks_like_imagefolder(path: Path) -> bool:
    class_directories = _visible_directories(path)
    return len(class_directories) >= 2 and sum(_has_direct_image(item) for item in class_directories) >= 2


def _nested_dataset(path: Path) -> Path | None:
    # A conservative one-level rule: dataset/dataset/class/image.  It intentionally
    # ignores train/val/test layouts and folders with several possible children.
    if _looks_like_imagefolder(path):
        return None
    children = _visible_directories(path)
    if len(children) == 1 and _looks_like_imagefolder(children[0]):
        return children[0]
    return None


def _path_role(parameter: dict[str, Any]) -> str | None:
    explicit = parameter.get("path_role")
    if explicit in {"input", "dataset", "output"}:
        return str(explicit)
    key = str(parameter.get("key", "")).split(".")[-1].lower()
    if key in OUTPUT_PATH_KEYS:
        return "output"
    if key in DATA_PATH_KEYS:
        return "dataset"
    return None


def _display_path(path: Path, original: str, root: Path) -> str:
    original_path = Path(os.path.expandvars(os.path.expanduser(original)))
    if original_path.is_absolute():
        return str(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def preflight_project(project: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """Validate a launch without importing or executing any project source code."""
    checked_values = dict(values)
    issues: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    root = Path(str(project.get("path", ""))).expanduser().resolve()
    adapter = project.get("adapter") or {}
    if not root.is_dir():
        issues.append(_issue("error", "project_missing", f"项目文件夹不存在：{root}"))
        return {"ok": False, "values": checked_values, "issues": issues, "changes": changes}

    entrypoint = (root / str(adapter.get("entrypoint") or project.get("entrypoint") or "")).resolve()
    if not entrypoint.is_file() or root not in entrypoint.parents:
        issues.append(_issue("error", "entrypoint_missing", f"训练入口不存在或不在项目中：{entrypoint}"))
    else:
        issues.append(_issue("info", "entrypoint_ok", f"训练入口有效：{entrypoint.name}"))

    python = _resolve_python(adapter.get("python"), root)
    if not python:
        issues.append(_issue("error", "python_missing", f"Python 解释器不存在或无法查找：{adapter.get('python') or '未设置'}"))
    else:
        try:
            version_result = _run_python(python, ["--version"], timeout=10)
            version = (version_result.stdout or version_result.stderr).strip()
            if version_result.returncode != 0:
                issues.append(_issue("error", "python_invalid", f"Python 解释器无法运行：{python}"))
            else:
                issues.append(_issue("info", "python_ok", f"解释器有效：{version or python}"))
                framework = str(adapter.get("framework") or project.get("framework") or "").lower()
                modules = FRAMEWORK_IMPORTS.get(framework, ())
                if modules:
                    script = (
                        "import importlib,sys\n"
                        f"mods={modules!r}\n"
                        "errors=[]\n"
                        "for name in mods:\n"
                        " try:\n"
                        "  module=importlib.import_module(name); print(name+' '+str(getattr(module,'__version__',''))); sys.exit(0)\n"
                        " except Exception as exc: errors.append(name+': '+str(exc))\n"
                        "print(' | '.join(errors), file=sys.stderr); sys.exit(1)\n"
                    )
                    import_result = _run_python(python, ["-c", script])
                    detail = (import_result.stdout or import_result.stderr).strip()
                    if import_result.returncode == 0:
                        issues.append(_issue("info", "framework_ok", f"框架依赖可用：{detail or framework}"))
                    else:
                        issues.append(_issue("error", "framework_missing", f"框架依赖无法导入：{detail or framework}"))
        except subprocess.TimeoutExpired:
            issues.append(_issue("error", "python_timeout", f"检查解释器或框架超时：{python}"))
        except OSError as exc:
            issues.append(_issue("error", "python_invalid", f"Python 解释器无法运行：{exc}"))

    parameters = {str(item.get("key")): item for item in adapter.get("parameters", [])}
    for key, parameter in parameters.items():
        value = checked_values.get(key)
        if parameter.get("required") and (value is None or value == ""):
            issues.append(_issue("error", "required_value_missing", f"必填参数 {key} 尚未填写", parameter=key))
            continue
        role = _path_role(parameter)
        if not role or value is None or value == "" or not isinstance(value, str):
            continue
        expanded = Path(os.path.expandvars(os.path.expanduser(value)))
        resolved = expanded.resolve() if expanded.is_absolute() else (root / expanded).resolve()
        if role == "output":
            existing_parent = resolved if resolved.exists() else resolved.parent
            if not existing_parent.exists():
                issues.append(_issue("warning", "output_parent_missing", f"输出目录的上级目录尚不存在，训练程序需要自行创建：{resolved}", parameter=key, original=value))
            continue
        if parameter.get("must_exist", True) is False:
            continue
        if not resolved.exists():
            issues.append(_issue("error", "input_path_missing", f"输入路径不存在：{resolved}", parameter=key, original=value))
            continue
        if role == "dataset" and resolved.is_dir():
            nested = _nested_dataset(resolved)
            if nested:
                suggested = _display_path(nested, value, root)
                checked_values[key] = suggested
                change = {
                    "parameter": key,
                    "original": value,
                    "suggested": suggested,
                    "reason": "外层目录只有一个子目录，真正的类别图片位于下一层",
                }
                changes.append(change)
                issues.append(_issue(
                    "warning", "nested_dataset", f"检测到数据集多嵌套一层：建议将 {key} 改为 {suggested}",
                    parameter=key, original=value, suggested=suggested,
                ))

    return {
        "ok": not any(item["level"] == "error" for item in issues),
        "values": checked_values,
        "issues": issues,
        "changes": changes,
    }
