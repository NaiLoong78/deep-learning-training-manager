import sys
import tempfile
import unittest
from pathlib import Path

from app.preflight import preflight_project


def make_project(root: Path, parameters: list[dict]) -> dict:
    (root / "train.py").write_text("print('training')\n", encoding="utf-8")
    return {
        "path": str(root),
        "entrypoint": "train.py",
        "framework": "Python",
        "adapter": {
            "entrypoint": "train.py",
            "framework": "Python",
            "python": sys.executable,
            "parameters": parameters,
        },
    }


def imagefolder(path: Path) -> None:
    for name in ("class_a", "class_b"):
        folder = path / name
        folder.mkdir(parents=True)
        (folder / "sample.jpg").write_bytes(b"not-an-image-but-enough-for-static-inspection")


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_normal_imagefolder_is_not_changed(self):
        imagefolder(self.root / "dataset")
        project = make_project(self.root, [{"key": "data_dir", "required": True}])

        result = preflight_project(project, {"data_dir": "dataset"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["values"]["data_dir"], "dataset")

    def test_nested_imagefolder_suggests_one_level_deeper(self):
        imagefolder(self.root / "dataset" / "dataset")
        project = make_project(self.root, [{"key": "data_dir"}])

        result = preflight_project(project, {"data_dir": "dataset"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["values"]["data_dir"], str(Path("dataset") / "dataset"))
        self.assertEqual(result["changes"][0]["parameter"], "data_dir")
        self.assertTrue(any(issue["code"] == "nested_dataset" for issue in result["issues"]))

    def test_missing_input_path_is_an_error(self):
        project = make_project(self.root, [{"key": "dataset_path"}])

        result = preflight_project(project, {"dataset_path": "does-not-exist"})

        self.assertFalse(result["ok"])
        self.assertTrue(any(issue["code"] == "input_path_missing" for issue in result["issues"]))

    def test_output_directory_is_not_treated_as_dataset(self):
        imagefolder(self.root / "results" / "results")
        project = make_project(self.root, [{"key": "output_dir"}])

        result = preflight_project(project, {"output_dir": "results"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["changes"], [])

    def test_missing_python_is_an_error(self):
        project = make_project(self.root, [])
        project["adapter"]["python"] = str(self.root / "missing-python.exe")

        result = preflight_project(project, {})

        self.assertFalse(result["ok"])
        self.assertTrue(any(issue["code"] == "python_missing" for issue in result["issues"]))


if __name__ == "__main__":
    unittest.main()
