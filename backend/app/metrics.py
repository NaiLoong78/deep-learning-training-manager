from __future__ import annotations

import json
import math
import re
from typing import Any


NUMBER = r"[+-]?(?:nan|inf(?:inity)?|(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)"
PAIR = re.compile(
    rf"(?P<name>(?:(?:train|training|val|valid|validation|test)[ _/.-]*)?"
    rf"(?:loss|accuracy|acc|lr|learning_rate|f1|map|iou|precision|recall))"
    rf"\s*[:=]\s*(?P<value>{NUMBER})\s*(?P<percent>%?)",
    re.I,
)
EPOCH = re.compile(r"epoch\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I)
EPOCH_BRACKET = re.compile(r"epoch\s*\[\s*(\d+)\s*/\s*(\d+)\s*\]", re.I)
STEP = re.compile(r"(?:step|iteration|iter)\s*[:=]?\s*(\d+(?:\.\d+)?)", re.I)
TRAIN_SUMMARY = re.compile(
    rf"train\s+loss\s*[:=]\s*(?P<loss>{NUMBER})\s*,\s*acc(?:uracy)?\s*[:=]\s*(?P<accuracy>{NUMBER})\s*(?P<percent>%?)",
    re.I,
)
VALIDATION_SUMMARY = re.compile(
    rf"(?:val|valid|validation)\s+loss\s*[:=]\s*(?P<loss>{NUMBER})\s*,\s*acc(?:uracy)?\s*[:=]\s*(?P<accuracy>{NUMBER})\s*(?P<percent>%?)",
    re.I,
)
LEARNING_RATE = re.compile(rf"(?:lr|learning[_ ]rate)\s*[:=]\s*(?P<value>{NUMBER})", re.I)


def _metric_number(value: str) -> float:
    return float(value)


def _summary_metrics(text: str) -> dict[str, Any] | None:
    train = TRAIN_SUMMARY.search(text)
    validation = VALIDATION_SUMMARY.search(text)
    if not train and not validation:
        return None
    result: dict[str, Any] = {}
    epoch = EPOCH_BRACKET.search(text)
    if epoch:
        result["epoch"] = float(epoch.group(1))
    learning_rate = LEARNING_RATE.search(text)
    if learning_rate:
        result["learning_rate"] = _metric_number(learning_rate.group("value"))
    if train:
        result["train/loss"] = _metric_number(train.group("loss"))
        result["train/accuracy"] = _metric_number(train.group("accuracy"))
    if validation:
        result["validation/loss"] = _metric_number(validation.group("loss"))
        result["validation/accuracy"] = _metric_number(validation.group("accuracy"))
    return result


def _normalize_name(name: str) -> str:
    words = [word for word in re.split(r"[ _/.-]+", name.strip().lower()) if word]
    if words in (["learning", "rate"], ["lr"]):
        return "learning_rate"
    aliases = {"training": "train", "val": "validation", "valid": "validation", "acc": "accuracy"}
    words = [aliases.get(word, word) for word in words]
    return "/".join(words)


def parse_metrics(line: str, prefix: str = "@@METRIC@@") -> dict[str, Any] | None:
    text = line.strip()
    if prefix and text.startswith(prefix):
        try:
            value = json.loads(text[len(prefix):].strip())
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None
    if text.startswith("{") and text.endswith("}"):
        try:
            value = json.loads(text)
            if isinstance(value, dict) and any(token in str(value).lower() for token in ("loss", "acc", "metric", "epoch")):
                return value
        except json.JSONDecodeError:
            pass
    summary = _summary_metrics(text)
    if summary:
        return summary
    # tqdm progress output can occur multiple times per batch. Epoch summaries
    # provide cleaner and substantially smaller chart data.
    if re.search(r"\d+\s*/\s*\d+\s*\[[^\]]*(?:it/s|s/it|\?it/s)", text, re.I):
        return None
    pairs = {_normalize_name(match.group("name")): _metric_number(match.group("value")) for match in PAIR.finditer(text)}
    if not pairs:
        return None
    epoch = EPOCH_BRACKET.search(text) or EPOCH.search(text)
    step = STEP.search(text)
    if epoch:
        pairs["epoch"] = float(epoch.group(1))
    if step:
        pairs["step"] = float(step.group(1))
    return pairs


def numeric_metrics(payload: dict[str, Any]) -> tuple[float | None, float | None, dict[str, float]]:
    epoch = payload.get("epoch")
    step = payload.get("step")
    reserved = {"epoch", "step", "timestamp", "message", "type"}
    metrics: dict[str, float] = {}
    nested = payload.get("metrics")
    source = nested if isinstance(nested, dict) else payload
    for key, value in source.items():
        if key in reserved or isinstance(value, bool):
            continue
        if isinstance(value, (int, float)) and math.isfinite(float(value)):
            metrics[str(key)] = float(value)
    return _number(epoch), _number(step), metrics


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None
