"""无需深度学习依赖的演示训练项目，用于验证管理平台完整链路。"""
import argparse
import json
import math
import os
import random
import time
from pathlib import Path


parser = argparse.ArgumentParser(description="Training manager demo")
parser.add_argument("--epochs", type=int, default=12, help="训练轮数")
parser.add_argument("--batch-size", type=int, default=32, choices=[8, 16, 32, 64, 128])
parser.add_argument("--learning-rate", type=float, default=0.001)
parser.add_argument("--optimizer", type=str, default="AdamW", choices=["SGD", "Adam", "AdamW"])
parser.add_argument("--seed", type=int, default=42)
parser.add_argument("--use-augmentation", action="store_true")
args = parser.parse_args()

random.seed(args.seed)
control_path = Path(os.environ.get("DL_MANAGER_CONTROL_FILE", "control.json"))
learning_rate = args.learning_rate
max_epochs = args.epochs

print(f"Demo training started: optimizer={args.optimizer}, batch_size={args.batch_size}")
for epoch in range(1, max_epochs + 1):
    if control_path.exists():
        try:
            control = json.loads(control_path.read_text(encoding="utf-8"))
            if control.get("stop_requested"):
                print("Graceful stop requested, saving checkpoint...")
                break
            learning_rate = float(control.get("learning_rate", control.get("lr", learning_rate)))
            max_epochs = int(control.get("epochs", control.get("max_epochs", max_epochs)))
        except (ValueError, json.JSONDecodeError):
            pass
    for step in range(1, 11):
        time.sleep(0.12)
        loss = 2.5 * math.exp(-(epoch * 10 + step) / 45) + random.random() * 0.04
        accuracy = min(0.99, 0.35 + (epoch * 10 + step) / 180 + random.random() * 0.02)
        print("@@METRIC@@" + json.dumps({
            "epoch": epoch,
            "step": (epoch - 1) * 10 + step,
            "train/loss": round(loss, 5),
            "train/accuracy": round(accuracy, 5),
            "learning_rate": learning_rate,
        }), flush=True)
    print(f"Epoch {epoch}/{max_epochs} finished - loss={loss:.4f} accuracy={accuracy:.4f}")

print("Training finished")

