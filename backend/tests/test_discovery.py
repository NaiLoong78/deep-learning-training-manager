from pathlib import Path

from app.discovery import inspect_project
from app.metrics import parse_metrics


def test_demo_discovery():
    demo = Path(__file__).resolve().parents[2] / "examples" / "demo-training-project"
    result = inspect_project(str(demo))
    assert result["entrypoint"] == "train.py"
    assert result["framework"] == "PyTorch"
    assert any(p["key"] == "learning_rate" for p in result["adapter"]["parameters"])


def test_metric_protocol():
    result = parse_metrics('@@METRIC@@{"epoch": 1, "train/loss": 0.5}')
    assert result and result["train/loss"] == 0.5

