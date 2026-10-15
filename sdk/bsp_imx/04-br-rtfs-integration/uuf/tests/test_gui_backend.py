"""GUI's host-only adapters retain the production geometry and archive checks."""

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from uuflib import cli, model


class MbrEditor(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.mapping = {
            "board": model.BOARD,
            "kernel": {"partition": 1, "path": "/zImage"},
            "dtb": {"partition": 1, "path": "/board.dtb"},
            "rtfs": {"partition": 2},
        }
        self.data = model.make_mbr(32 * 1024**2, 64 * 1024**2, self.mapping, "12345678")
        self.source = self.root / "original.bin"
        self.source.write_bytes(self.data)
        self.targets = self.root / "targets.json"
        self.targets.write_text(json.dumps(self.mapping))
        self.entries = [
            {k: p[k] for k in ("number", "start", "sectors")}
            for p in model.parse_mbr(self.data)["entries"]
        ]

    def tearDown(self):
        self.temp.cleanup()

    def run_editor(self, entries=None, signature="12345678"):
        args = ["mbr", "--input", str(self.source), "--targets", str(self.targets)]
        if entries is not None:
            args += [
                "--entries",
                json.dumps(entries),
                "--signature",
                signature,
                "--output",
                str(self.root / "edited.bin"),
            ]
        events = []
        cli.dispatch(
            vars(cli.parser().parse_args(args)),
            lambda k, d: events.append((k, d)),
            None,
        )
        return events[-1][1]

    def test_read_and_edit_preserve_input_and_validate_with_shared_geometry(self):
        self.assertEqual(self.run_editor()["signature"], "12345678")
        self.entries[1]["sectors"] *= 2
        result = self.run_editor(self.entries, "87654321")
        self.assertEqual(result["entries"][1]["sectors"], self.entries[1]["sectors"])
        self.assertEqual(self.source.read_bytes(), self.data)
        model.geometry((self.root / "edited.bin").read_bytes(), self.mapping)
        self.assertEqual(result["signature"], "87654321")
        with self.assertRaises(FileExistsError):
            self.run_editor(self.entries)

    def test_overlap_invalid_alignment_and_role_changes_never_create_output(self):
        for key, value in [
            ("start", 2048),
            ("start", 67585),
            ("number", 3),
            ("sectors", -8),
        ]:
            with self.subTest(key=key, value=value):
                entries = json.loads(json.dumps(self.entries))
                entries[1][key] = value
                with self.assertRaises(ValueError):
                    self.run_editor(entries)
                self.assertFalse((self.root / "edited.bin").exists())

    def test_zero_signature_never_creates_output(self):
        with self.assertRaises(ValueError):
            self.run_editor(self.entries, "00000000")
        self.assertFalse((self.root / "edited.bin").exists())


if __name__ == "__main__":
    unittest.main()
