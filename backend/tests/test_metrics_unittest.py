import math
import unittest

from app.metrics import numeric_metrics, parse_metrics


class MetricParsingTests(unittest.TestCase):
    def test_epoch_summary_with_train_and_validation_metrics(self):
        line = (
            "Epoch [03/20] Time: 12.4s | LR: 0.000100 | "
            "Train Loss: 0.4567, Acc: 82.30% | Val Loss: 0.5123, Acc: 79.80%"
        )

        result = parse_metrics(line)

        self.assertIsNotNone(result)
        self.assertEqual(result["epoch"], 3.0)
        self.assertEqual(result["learning_rate"], 0.0001)
        self.assertEqual(result["train/loss"], 0.4567)
        self.assertEqual(result["train/accuracy"], 82.30)
        self.assertEqual(result["validation/loss"], 0.5123)
        self.assertEqual(result["validation/accuracy"], 79.80)

    def test_non_finite_values_are_not_written_as_metrics(self):
        result = parse_metrics(
            "Epoch [01/5] LR: 0.01 | Train Loss: nan, Acc: 4.76% | Val Loss: 100.0, Acc: 4.14%"
        )
        self.assertIsNotNone(result)
        self.assertTrue(math.isnan(result["train/loss"]))

        epoch, _, metrics = numeric_metrics(result)

        self.assertEqual(epoch, 1.0)
        self.assertNotIn("train/loss", metrics)
        self.assertEqual(metrics["validation/accuracy"], 4.14)

    def test_common_single_metrics_are_supported(self):
        result = parse_metrics("epoch=2 loss=0.5 accuracy=0.8 learning_rate=1e-4")

        self.assertEqual(result["epoch"], 2.0)
        self.assertEqual(result["loss"], 0.5)
        self.assertEqual(result["accuracy"], 0.8)
        self.assertEqual(result["learning_rate"], 0.0001)

    def test_tqdm_refresh_is_not_saved_for_every_batch(self):
        result = parse_metrics("Epoch [1/5] Train: 20%|## | 60/308 [00:20<01:00, 2.4it/s, Loss=2.9]")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
