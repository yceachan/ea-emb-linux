"""Exercise the host CLI against a pseudo-terminal and recorded UUU traces."""

import hashlib
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest


BSP = Path(__file__).resolve().parents[1]


class HostWorkflowTests(unittest.TestCase):
    def run_workflow(self, mode, case="success"):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            work = root / "artifacts"
            work.mkdir()
            for name in ("ram-boot.uuu", "emmc-flash.uuu"):
                shutil.copyfile(BSP / name, work / name)
            shutil.copyfile(BSP / "evidence/2026-10-06-uuu/u-boot-dtb.imx", work / "u-boot-dtb.imx")
            (work / "SHA256SUMS").write_text("".join(
                f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}\n"
                for file in sorted(work.iterdir())
            ))
            if case == "bad_hash":
                (work / "u-boot-dtb.imx").write_bytes(b"wrong image")

            # Real, archived UUU output exercises formatting and ANSI handling.
            source = ("2026-10-06-mbr/uuu.log" if mode == "ram"
                      else "2026-10-06-emmc/uuu-emmc.log")
            (root / "trace").write_bytes((BSP / "evidence" / source).read_bytes())
            fake = root / "uuu"
            fake.write_text("""#!/usr/bin/env python3
import os, pathlib, sys, time
root = pathlib.Path(os.environ['FAKE_ROOT'])
case = os.environ['FAKE_CASE']
args = sys.argv[1:]
if '-lsusb' in args:
    if case != 'no_rom':
        print('3:1 MX6ULL SDP: 0x15a2 0x0080 0x0001')
    if case == 'two_roms':
        print('3:2 MX6ULL SDP: 0x15a2 0x0080 0x0001')
elif '-dry' in args:
    print('Error: invalid input' if case == 'dry_failure' else 'Parsed script')
else:
    assert args[:3] == ['-v', '-m', '3:1'], args
    (root / 'started').touch()
    if case == 'hidden_failure':
        print('Error: USB write failed', flush=True)
        sys.exit(0)  # Reproduce the installed Snap launcher behavior.
    if args[-1] == 'emmc-flash.uuu':
        while not (root / 'fastboot').exists():
            time.sleep(.01)
    sys.stdout.buffer.write((root / 'trace').read_bytes())
    sys.stdout.buffer.flush()
    if case == 'nonzero':
        sys.exit(1)
""")
            fake.chmod(0o755)
            master, slave = pty.openpty()
            commands = bytearray()
            stop = threading.Event()
            errors = []

            def board():
                try:
                    while not stop.is_set() and not (root / "started").exists():
                        stop.wait(.01)
                    if stop.is_set():
                        return
                    banner = b"\r\nU-Boot 2026.07\r\nBoard: 100ask i.MX6ULL Pro (UART1 / eMMC)\r\n"
                    if case != "stale_prompt":
                        os.write(master, banner)
                    # Fragment the prompt across UART deliveries.
                    os.write(master, b"=")
                    time.sleep(.02)
                    os.write(master, b"> ")
                    while not stop.is_set():
                        if not select.select([master], [], [], .05)[0]:
                            continue
                        data = os.read(master, 1024)
                        commands.extend(data)
                        if b"fastboot usb 0\r" in commands and not (root / "fastboot").exists():
                            size = 351231 if case == "wrong_comparison" else 351232
                            os.write(master, f"\r\nTotal of {size} byte(s) were the same\r\n".encode())
                            (root / "fastboot").touch()
                        if b"\x03" in data and case != "stuck_fastboot":
                            os.write(master, b"\r\n=> ")
                except OSError as error:
                    if not stop.is_set():
                        errors.append(error)

            thread = threading.Thread(target=board)
            thread.start()
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ["PATH"],
                       FAKE_ROOT=str(root), FAKE_CASE=case)
            try:
                result = subprocess.run(
                    [sys.executable, str(BSP / "uboot.py"), mode, "--no-console",
                     "--artifacts", str(work), "--serial", os.ttyname(slave),
                     "--log-dir", str(root / "logs"), "--timeout", "1"],
                    env=env, capture_output=True, timeout=8,
                )
                # Capture final Ctrl-C before shutting down the board emulator.
                time.sleep(.05)
                started = (root / "started").exists()
                log = root / "logs/uuu.log"
                trace = log.read_bytes() if log.exists() else b""
            finally:
                stop.set()
                thread.join(timeout=2)
                os.close(master)
                os.close(slave)
            self.assertFalse(thread.is_alive())
            self.assertFalse(errors)
            return result, bytes(commands), started, trace

    def test_ram_leaves_console_without_fastboot(self):
        result, commands, _, trace = self.run_workflow("ram")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, b"")
        self.assertIn(b"Start Cmd:SDP: done", trace)

    def test_emmc_enters_fastboot_once_and_releases_console(self):
        result, commands, _, trace = self.run_workflow("emmc")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(commands, b"fastboot usb 0\r\x03")
        self.assertIn(b"Start Cmd:FB: Done", trace)

    def test_zero_exit_with_uuu_error_is_failure(self):
        result, _, _, _ = self.run_workflow("emmc", "hidden_failure")
        self.assertEqual(result.returncode, 1)
        self.assertIn("UUU 报告失败".encode(), result.stderr)

    def test_old_prompt_does_not_trigger_flashing(self):
        result, commands, _, _ = self.run_workflow("emmc", "stale_prompt")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(commands, b"")

    def test_missing_full_comparison_is_failure(self):
        result, commands, _, _ = self.run_workflow("emmc", "wrong_comparison")
        self.assertEqual(result.returncode, 1)
        self.assertIn("逐字节比较".encode(), result.stderr)
        self.assertTrue(commands.endswith(b"\x03"))

    def test_nonzero_exit_is_failure_even_with_complete_trace(self):
        result, _, _, _ = self.run_workflow("emmc", "nonzero")
        self.assertEqual(result.returncode, 1)

    def test_successful_flash_requires_return_to_console(self):
        result, commands, _, _ = self.run_workflow("emmc", "stuck_fastboot")
        self.assertEqual(result.returncode, 1)
        self.assertIn("退出 fastboot".encode(), result.stderr)
        self.assertTrue(commands.endswith(b"\x03"))

    def test_preflight_failures_never_start_transfer(self):
        for case in ("bad_hash", "dry_failure", "no_rom", "two_roms"):
            with self.subTest(case=case):
                result, commands, started, _ = self.run_workflow("emmc", case)
                self.assertEqual(result.returncode, 1)
                self.assertFalse(started)
                self.assertEqual(commands, b"")


if __name__ == "__main__":
    unittest.main()
