"""Firmware-only deployment must need no system/rootfs package or real USB write."""
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

UBOOT = Path(__file__).resolve().parents[1]
BUILD = UBOOT.parent / "build/uboot"
BUILD.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(UBOOT / "tools"))
import firmware
from images import write_sums

spec = importlib.util.spec_from_file_location("boot_flash", UBOOT / "flash.py")
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class BootloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-bootloader-", dir=BUILD)
        self.root = Path(self.temp.name)
        self.fw = self.root / "firmware"
        self.fw.mkdir()
        (self.fw / "u-boot-dtb.imx").write_bytes(b"\xd1\x00\x20\x40" + bytes(4092))
        (self.fw / ".config").write_text("".join(f"{k}={v}\n" for k, v in firmware.OPTIONS.items()))
        (self.fw / "source-revision").write_text((UBOOT / "base-revision").read_text())
        (self.fw / "bsp-inputs.sha256").write_text(firmware.inputs(UBOOT))
        (self.fw / "image-info.txt").write_text("SYNTHETIC TEST ONLY\n")
        write_sums(self.fw)
        self.marker = self.root / "calls"
        self.fake = self.root / "fake-uuu"
        self.fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with pathlib.Path(os.environ['CALLS']).open('a') as f:
    f.write(json.dumps(args) + '\\n')
if args == ['-h']:
    print('libuuu_1.5.21-0-test')
elif args == ['-lsusb']:
    print('3:1 MX6ULL SDP: 0x15a2 0x0080 0x0001')
else:
    text = pathlib.Path(args[-1]).read_text()
    assert 'flash all ' not in text and 'fatwrite' not in text
    lines = [line for line in text.splitlines() if line.startswith(('SDP:', 'FB:'))]
    if '-dry' in args:
        print('\\n'.join(lines))
    elif os.environ.get('FAIL') == '1':
        print('Error: simulated write failure')
    else:
        for line in lines:
            print('Start Cmd:' + line)
            print('Okay')
''')
        self.fake.chmod(0o755)

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *, dry=False, real=False, confirm=None, fail=False):
        log = self.root / ("logs-" + str(time.monotonic_ns()))
        args = [sys.executable, str(UBOOT / "flash.py"), "bootloader", "--firmware", str(self.fw),
                "--uuu", shutil.which("uuu") if real else str(self.fake), "--log-dir", str(log)]
        if dry:
            args.append("--dry-run")
        env = dict(os.environ, CALLS=str(self.marker), FAIL="1" if fail else "0")
        if confirm is None:
            result = subprocess.run(args, env=env, capture_output=True, timeout=20)
            status, output = result.returncode, result.stdout + result.stderr
        else:
            master, slave = pty.openpty()
            proc = subprocess.Popen(args, env=env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            os.close(slave)
            output = bytearray()
            sent = False
            deadline = time.monotonic() + 20
            try:
                while proc.poll() is None:
                    if time.monotonic() > deadline:
                        raise AssertionError("confirmation timed out")
                    if select.select([proc.stdout], [], [], .1)[0]:
                        output.extend(os.read(proc.stdout.fileno(), 65536))
                    if not sent and "输入 WRITE".encode() in output:
                        os.write(master, (confirm + "\n").encode())
                        sent = True
                output.extend(proc.stdout.read())
                status = proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
                os.close(master)
        calls = [json.loads(x) for x in self.marker.read_text().splitlines()] if self.marker.exists() else []
        return status, bytes(output), calls, log

    def test_dry_needs_only_firmware_and_has_exact_write_scope(self):
        status, output, calls, log = self.run_cli(dry=True)
        self.assertEqual(status, 0, output.decode())
        self.assertTrue(all(x == ['-h'] or x[0] == '-dry' for x in calls), calls)
        text = (log / "run/task.uuu").read_text()
        writes = [x for x in text.splitlines() if x.startswith('FB: flash') or 'partconf' in x or 'fatwrite' in x]
        self.assertEqual(writes, ['FB: flash bootloader product.imx', 'FB: ucmd mmc partconf 1 1 1 0'])
        self.assertEqual(text.count('imx04 loadersave '), 1024)
        self.assertEqual(text.count('imx04 keep '), 1024)
        self.assertLess(text.index('imx04 loaderguard'), text.index(writes[0]))
        self.assertGreater(text.index('imx04 verify 1 2 '), text.index(writes[0]))
        self.assertEqual(set(p.name for p in (log / 'run').iterdir()), firmware.BOOT_REQUIRED | {'task.uuu', 'SHA256SUMS'})
        self.assertNotIn('layout', json.loads((log / 'preflight.json').read_text()))

    def test_actual_uuu_dry_run_without_rootfs_or_usb(self):
        if shutil.which('uuu') is None:
            self.skipTest('UUU not installed')
        status, output, _, log = self.run_cli(dry=True, real=True)
        self.assertEqual(status, 0, output.decode())
        self.assertFalse((log / 'usb.log').exists())
        self.assertFalse((log / 'uuu.log').exists())

    def test_bad_hash_or_stale_source_never_invokes_uuu(self):
        (self.fw / 'u-boot-dtb.imx').write_bytes(b'bad')
        status, _, calls, _ = self.run_cli(dry=True)
        self.assertEqual(status, 1)
        self.assertEqual(calls, [])
        (self.fw / 'u-boot-dtb.imx').write_bytes(b'\xd1\x00\x20\x40' + bytes(4092))
        (self.fw / 'bsp-inputs.sha256').write_text('stale inputs\n')
        (self.fw / 'SHA256SUMS').unlink()
        write_sums(self.fw)
        status, _, calls, _ = self.run_cli(dry=True)
        self.assertEqual(status, 1)
        self.assertEqual(calls, [])

    def test_no_tty_or_cancel_cannot_write(self):
        for confirm in (None, 'NO'):
            status, output, calls, _ = self.run_cli(confirm=confirm)
            self.assertEqual(status, 1 if confirm is None else 0, output.decode())
            self.assertFalse(any('-v' in call for call in calls))

    def test_confirmed_fake_transfer_checks_bootconf_and_protection(self):
        status, output, calls, log = self.run_cli(confirm='WRITE 3:1')
        self.assertEqual(status, 0, output.decode())
        transfers = [call for call in calls if '-v' in call]
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0][:4], ['-v', '-m', '3:1', '-t'])
        self.assertEqual(json.loads((log / 'result.json').read_text())['cold_boot'], 'pending')

    def test_hidden_failure_does_not_create_success_result(self):
        status, output, _, log = self.run_cli(confirm='WRITE 3:1', fail=True)
        self.assertEqual(status, 1, output.decode())
        self.assertFalse((log / 'result.json').exists())


if __name__ == '__main__':
    unittest.main()
