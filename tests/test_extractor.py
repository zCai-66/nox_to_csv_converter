from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nox_csv_extractor.gui import extract_target, main, resolve_output_csv_path
from nox_csv_extractor.nox import NoxNumericTable, write_nox_table_csv


class AppTests(unittest.TestCase):
    def test_main_starts_tk_app(self) -> None:
        with patch("nox_csv_extractor.gui.NoxToCsvApp") as app_class:
            app = app_class.return_value
            self.assertEqual(main(), 0)
            app.mainloop.assert_called_once_with()

    def test_resolve_output_csv_path_existing_policies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            nox = Path(tmp) / "sample.nox"
            nox.write_bytes(b"placeholder")
            csv = nox.with_suffix(".csv")
            self.assertEqual(resolve_output_csv_path(nox), csv)

            csv.write_text("existing", encoding="utf-8")
            self.assertEqual(resolve_output_csv_path(nox, "rename"), Path(tmp) / "sample_2.csv")
            (Path(tmp) / "sample_2.csv").write_text("existing", encoding="utf-8")
            self.assertEqual(resolve_output_csv_path(nox, "rename"), Path(tmp) / "sample_3.csv")
            self.assertEqual(resolve_output_csv_path(nox, "overwrite"), csv)
            self.assertIsNone(resolve_output_csv_path(nox, "skip"))

    def test_extract_target_recurses_and_writes_in_place(self) -> None:
        table = NoxNumericTable("mock", ["Time (s)", "Current (A)"], [[0.0, 1.0]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "nested"
            nested.mkdir()
            source = nested / "sample.nox"
            source.write_bytes(b"mock")

            with patch("nox_csv_extractor.gui.extract_nox_numeric_table", return_value=table):
                results = extract_target(root)

            self.assertEqual(results[0].status, "ok")
            self.assertTrue(source.with_suffix(".csv").exists())

    def test_extract_target_skip_existing_marks_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.nox"
            source.write_bytes(b"mock")
            source.with_suffix(".csv").write_text("existing", encoding="utf-8")

            results = extract_target(source, on_existing="skip")

            self.assertEqual(results[0].status, "skipped")

    def test_extract_target_empty_folder_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                extract_target(Path(tmp))

    def test_write_csv_uses_utf8_sig_and_headers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            table = NoxNumericTable("mock", ["Time (s)", "Current (A)"], [[0.0, 1.0]])
            output = write_nox_table_csv(table, Path(tmp) / "out.csv")
            content = output.read_text(encoding="utf-8-sig")
            self.assertIn("Time (s),Current (A)", content)


if __name__ == "__main__":
    unittest.main()
