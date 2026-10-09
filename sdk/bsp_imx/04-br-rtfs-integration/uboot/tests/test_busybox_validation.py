"""Archive rejection and image-role tests; no board access or SDK build."""
import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

UBOOT = Path(__file__).resolve().parents[1]
BUILD = UBOOT.parent / "build/uboot"
BUILD.mkdir(parents=True, exist_ok=True)
spec = importlib.util.spec_from_file_location("busybox_prepare", UBOOT / "busybox-validation/prepare.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class BusyBoxArchiveTests(unittest.TestCase):
    def make_tar(self, path, items):
        with tarfile.open(path, "w") as archive:
            for name, kind, link in items:
                info = tarfile.TarInfo(name)
                info.uid = info.gid = 0
                info.type = kind
                info.linkname = link
                info.size = 1 if kind == tarfile.REGTYPE else 0
                archive.addfile(info, io.BytesIO(b"x") if info.size else None)

    def rejected(self, items):
        with tempfile.TemporaryDirectory(dir=BUILD) as temp:
            root = Path(temp)
            self.make_tar(root / "archive", items)
            with self.assertRaises(ValueError):
                prepare.extract_tree(root / "archive", root / "tree")
            self.assertFalse((root / "tree").exists())

    def test_path_escape_is_rejected_before_extraction(self):
        self.rejected([("../escape", tarfile.REGTYPE, "")])
        self.rejected([("/escape", tarfile.REGTYPE, "")])

    def test_parent_symlink_write_is_rejected(self):
        self.rejected([("etc", tarfile.SYMTYPE, "/tmp"), ("etc/escape", tarfile.REGTYPE, "")])

    def test_special_and_duplicate_entries_are_rejected(self):
        self.rejected([("node", tarfile.CHRTYPE, "")])
        self.rejected([("hard", tarfile.LNKTYPE, "target")])
        self.rejected([("same", tarfile.REGTYPE, ""), ("same", tarfile.REGTYPE, "")])

    def test_verifier_has_no_persistent_write_operations(self):
        text = (UBOOT / "busybox-validation/verify-board.sh").read_text()
        # Relevant negative invariants: it reads the real FAT block device and
        # must not validate stale p2 /boot copies or reboot/mount the board.
        self.assertIn("sha256sum /dev/mmcblk1p1", text)
        self.assertNotIn("sha256sum /boot/", text)
        commands = [line.strip().split()[0] for line in text.splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
        self.assertFalse(set(commands) & {"mount", "reboot", "dd", "mkfs", "fatwrite"})


if __name__ == "__main__":
    unittest.main()
