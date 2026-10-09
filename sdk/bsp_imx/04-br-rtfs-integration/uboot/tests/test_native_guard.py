"""Run actual production guard code with fake storage; no U-Boot build/USB."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

BSP = Path(__file__).resolve().parents[1]
BUILD = BSP.parent / "build/uboot"
BUILD.mkdir(parents=True, exist_ok=True)


class NativeGuardTests(unittest.TestCase):
    def test_production_read_guards_fail_closed(self):
        if shutil.which("cc") is None:
            self.skipTest("host C compiler not available")
        BUILD.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="test-guard-", dir=BUILD) as temp:
            root = Path(temp)
            headers = ["command.h", "fat.h", "malloc.h", "memalign.h", "mmc.h", "part.h",
                       "stdlib.h", "vsprintf.h", "asm/unaligned.h", "u-boot/sha256.h", "linux/delay.h"]
            # Do not shadow system stdlib.h; production already sees it through mock.h.
            headers.remove("stdlib.h")
            for name in headers:
                file = root / name
                file.parent.mkdir(exist_ok=True, parents=True)
                file.write_text('#include "guard_mock.h"\n')
            source = BSP / "overlay/board/100ask/imx6ull/update_guard.c"
            compile_result = subprocess.run(
                ["cc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter",
                 "-Wno-deprecated-declarations", "-I", str(root), "-I", str(BSP / "tests"),
                 f'-DIMX04_SOURCE="{source}"', str(BSP / "tests/test_guard.c"),
                 "-lcrypto", "-o", str(root / "guard")], capture_output=True, timeout=30)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr.decode())
            result = subprocess.run([str(root / "guard")], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())


if __name__ == "__main__":
    unittest.main()
