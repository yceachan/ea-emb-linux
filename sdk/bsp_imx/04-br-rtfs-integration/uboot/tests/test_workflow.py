"""Safety tests use host files, fake UUU and synthetic firmware; never real USB writes."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest

BSP = Path(__file__).resolve().parents[1]
BUILD = BSP.parent / "build/uboot"
BUILD.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(BSP / "tools"))
import firmware
from images import (BLOCK, BOOTCONF, DTB, FILL, RAW, SKIP, REQUIRED, Sparse, command,
                    encode_sparse, ext4_allocated, layout, preflight_images, sha256, verify_sums, write_sums)

spec = importlib.util.spec_from_file_location("flash", BSP / "flash.py")
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)


class SparseTests(unittest.TestCase):
    def test_meaningful_zero_block_is_written_and_free_block_is_skipped(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as temp:
            root = Path(temp)
            (root / "raw").write_bytes(bytes(BLOCK) + b"live" * (BLOCK // 4) + bytes(BLOCK))
            encode_sparse(root / "raw", root / "sparse", 3, [(0, 2)])
            image = Sparse(root / "sparse")
            self.assertEqual([x.kind for x in image.chunks], [RAW, SKIP])
            self.assertTrue(image.covers([(0, 2)]))
            self.assertFalse(image.covers([(0, 3)]))
            image.extract(root / "expanded")
            self.assertEqual((root / "raw").read_bytes(), (root / "expanded").read_bytes())
            encode_sparse(root / "raw", root / "zeros", 3, [(0, 1)])
            self.assertEqual(Sparse(root / "zeros").chunks[0].kind, FILL)
            self.assertEqual(list(Sparse(root / "zeros").checks())[0][1], 8)

    def test_independent_aosp_decoder_agrees_on_raw_fill_and_skip(self):
        if shutil.which("simg2img") is None:
            self.skipTest("AOSP simg2img not installed")
        with tempfile.TemporaryDirectory(dir=BUILD) as temp:
            root = Path(temp)
            live = bytes(range(256)) * (BLOCK // 256)
            raw = bytes(BLOCK) + live + b"stale!!!" * (BLOCK // 8) + b"\xff" * BLOCK
            (root / "raw").write_bytes(raw)
            encode_sparse(root / "raw", root / "sparse", 4, [(0, 1), (1, 2), (3, 4)])
            self.assertEqual([c.kind for c in Sparse(root / "sparse").chunks], [FILL, RAW, SKIP, FILL])
            command(["simg2img", root / "sparse", root / "expanded"])
            self.assertEqual((root / "expanded").read_bytes(), bytes(BLOCK) + live + bytes(BLOCK) + b"\xff" * BLOCK)

    def test_truncation_overflow_unknown_chunks_and_trailing_data_are_rejected(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as temp:
            path = Path(temp) / "sparse"
            header = struct.pack("<I4H4I", 0xED26FF3A, 1, 0, 28, 12, BLOCK, 1, 1, 0)
            samples = [b"", header, header + struct.pack("<2H2I", RAW, 0, 1, 4108),
                       header + struct.pack("<2H2I", SKIP, 0, 2, 12),
                       header + struct.pack("<2H2I", 0xCAFE, 0, 1, 12),
                       header + struct.pack("<2H2I", SKIP, 0, 1, 12) + b"tail"]
            for sample in samples:
                path.write_bytes(sample)
                with self.subTest(sample=sample[:40]), self.assertRaises(ValueError):
                    Sparse(path)


class HostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        BUILD.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix="test-host-", dir=BUILD)
        cls.root = Path(cls.temp.name)
        cls.package = cls.root / "package"
        fw = cls.root / "firmware"
        fw.mkdir()
        # Deliberately synthetic .imx; these fixtures prove packaging/guards only.
        (fw / "u-boot-dtb.imx").write_bytes(b"\xd1\x00\x20\x40" + b"TEST ONLY" + bytes(4096 - 13))
        (fw / ".config").write_text("\n".join(f"{k}={v}" for k, v in firmware.OPTIONS.items()) + "\n")
        (fw / "source-revision").write_text((BSP / "base-revision").read_text())
        (fw / "bsp-inputs.sha256").write_text(firmware.inputs(BSP))
        (fw / "image-info.txt").write_text("SYNTHETIC FIRMWARE: NOT FOR A BOARD\n")
        write_sums(fw)
        kernel = cls.root / "zImage"
        kernel.write_bytes(bytes(36) + struct.pack("<I", 0x016F2818) + bytes(4096 - 40))
        (cls.root / "board.dts").write_text('/dts-v1/; / { model = "test"; compatible = "test"; };\n')
        command(["dtc", "-I", "dts", "-O", "dtb", "-o", cls.root / DTB, cls.root / "board.dts"])
        rootfs = cls.root / "rootfs.ext4"
        with rootfs.open("wb") as f:
            f.truncate(layout(BSP / "layout.json")["p2"]["sectors"] * 512)
        command(["mkfs.ext4", "-q", "-F", "-b", "4096", "-E",
                 "lazy_itable_init=0,lazy_journal_init=0", rootfs])
        result = subprocess.run([sys.executable, str(BSP / "package.py"), "--firmware", str(fw),
                                 "--kernel", str(kernel), "--dtb", str(cls.root / DTB),
                                 "--rootfs", str(rootfs), "--output", str(cls.package)],
                                capture_output=True, timeout=120)
        if result.returncode:
            raise RuntimeError(result.stdout.decode() + result.stderr.decode())
        cls.config = layout(cls.package / "layout.json")
        cls.system = Sparse(cls.package / "system.sparse.img")
        cls.rootfs = Sparse(cls.package / "rootfs.sparse.img")
        cls.fake = cls.root / "uuu-fake"
        cls.fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
marker = pathlib.Path(os.environ['CALLS'])
with marker.open('a') as f:
    f.write(json.dumps(args) + '\\n')
case = os.environ.get('CASE', 'success')
if '-lsusb' in args:
    print('3:1 MX6ULL SDP: 0x15a2 0x0080 0x0001')
elif '-h' in args:
    print('uuu (Universal Update Utility) -- libuuu_1.5.21-0-test')
elif case == 'hang':
    time.sleep(60)
else:
    lines = [x for x in pathlib.Path(args[-1]).read_text().splitlines() if x.startswith(('SDP:', 'FB:'))]
    if '-dry' in args:
        print('\\n'.join(lines))
    elif case == 'hidden_failure':
        print('Error: device write failed')
    else:
        if case == 'incomplete':
            lines = lines[:-1]
        for line in lines:
            print('Start Cmd:' + line)
            print('Okay')
        if case == 'nonzero':
            sys.exit(1)
''')
        cls.fake.chmod(0o755)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_four_modes_have_exact_write_scope_and_protection(self):
        for mode in ("all", "kernel", "dtb", "rootfs"):
            with self.subTest(mode=mode):
                text = flash.script_for(mode, self.package, self.config, self.system, self.rootfs)
                writes = [x for x in text.splitlines() if x.startswith("FB: flash") or "fatwrite" in x or "partconf" in x]
                if mode == "all":
                    self.assertEqual(writes, ["FB: flash all system.sparse.img", "FB: flash bootloader product.imx", "FB: ucmd mmc partconf 1 1 1 0"])
                    self.assertIn("FB: ucmd imx04 bootconf 48", text)
                elif mode == "rootfs":
                    self.assertEqual(writes, ["FB: flash rootfs rootfs.sparse.img"])
                    self.assertIn("FB: ucmd imx04 bootkeep", text)
                else:
                    name = "zImage" if mode == "kernel" else DTB
                    self.assertEqual(writes, [f"FB: ucmd fatwrite mmc 1:1 0x82000000 {name} ${{filesize}}"])
                    self.assertIn(f"FB: ucmd imx04 space {name}", text)
                    self.assertIn(f"FB: ucmd imx04 file {name}", text)
                if mode != "all":
                    self.assertIn("FB: ucmd imx04 save 0 1 0 0", text)
                    self.assertEqual(text.count("FB: ucmd imx04 keep"), text.count("FB: ucmd imx04 save") + text.count("FB: ucmd imx04 filesave"))
                    self.assertLess(text.rindex("FB: ucmd imx04 filesave") if mode != "rootfs" else text.rindex("FB: ucmd imx04 save"), text.index(writes[0]))

    def test_real_installed_uuu_parses_all_four_scripts_without_hardware(self):
        executable = shutil.which("uuu")
        if executable is None:
            self.skipTest("UUU not installed")
        for mode in ("all", "kernel", "dtb", "rootfs"):
            script = self.package / "test.uuu"
            script.write_text(flash.script_for(mode, self.package, self.config, self.system, self.rootfs))
            result = subprocess.run([executable, "-dry", script.name], cwd=self.package,
                                    capture_output=True, timeout=20)
            text = flash.plain(result.stdout + result.stderr)
            self.assertEqual(result.returncode, 0, text)
            self.assertFalse(flash.failed(text), text)
            self.assertTrue(flash.complete(text, script, dry=True), text[-2000:])
        script.unlink()

    def test_real_uuu_full_cli_dry_run(self):
        executable = shutil.which("uuu")
        if executable is None:
            self.skipTest("UUU not installed")
        result = subprocess.run([sys.executable, str(BSP / "flash.py"), "--all",
                                 "--package", str(self.package), "--uuu", executable,
                                 "--log-dir", str(self.root / "real-cli-logs"), "--dry-run"], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout.decode() + result.stderr.decode())
        self.assertIn("没有枚举 USB".encode(), result.stdout)

    def test_all_flag_rejects_a_second_operation(self):
        result = subprocess.run([sys.executable, str(BSP / "flash.py"), "--all", "bootloader"],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--all 与位置操作不可同时使用".encode(), result.stderr)

    def cli(self, *, case="success", dry=False, confirm=None):
        marker = self.root / ("calls-" + str(time.monotonic_ns()))
        env = dict(os.environ, CALLS=str(marker), CASE=case)
        args = [sys.executable, str(BSP / "flash.py"), "rtfs", "--package", str(self.package),
                "--uuu", str(self.fake), "--log-dir", str(marker) + "-logs"]
        if dry:
            args.append("--dry-run")
        if confirm is None:
            result = subprocess.run(args, env=env, capture_output=True, timeout=60)
            output, status = result.stdout + result.stderr, result.returncode
        else:
            master, slave = pty.openpty()
            process = subprocess.Popen(args, env=env, stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            os.close(slave)
            output = bytearray()
            deadline = time.monotonic() + 60
            sent = False
            try:
                while process.poll() is None:
                    if time.monotonic() > deadline:
                        raise AssertionError("confirmation workflow timed out")
                    if select.select([process.stdout], [], [], .1)[0]:
                        output.extend(os.read(process.stdout.fileno(), 65536))
                    if not sent and "输入 WRITE".encode() in output:
                        os.write(master, (confirm + "\n").encode())
                        sent = True
                output.extend(process.stdout.read())
                status = process.wait()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()
                os.close(master)
        calls = [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []
        return status, bytes(output), calls

    def test_dry_run_never_enumerates_or_transfers_and_rtfs_alias_works(self):
        status, output, calls = self.cli(dry=True)
        self.assertEqual(status, 0, output.decode())
        self.assertTrue(all(x[0] == "-dry" or x == ["-h"] for x in calls), calls)
        self.assertIn("操作：rootfs".encode(), output)

    def test_noninteractive_or_cancelled_run_cannot_transfer(self):
        for confirmation in (None, "NO"):
            status, output, calls = self.cli(confirm=confirmation)
            self.assertEqual(status, 1 if confirmation is None else 0, output.decode())
            self.assertFalse(any("-v" in x for x in calls), calls)

    def test_confirmation_precedes_single_path_pinned_transfer(self):
        status, output, calls = self.cli(confirm="WRITE 3:1")
        self.assertEqual(status, 0, output.decode())
        transfers = [x for x in calls if "-v" in x]
        self.assertEqual(len(transfers), 1, calls)
        self.assertEqual(transfers[0][:4], ["-v", "-m", "3:1", "-t"])
        self.assertEqual(sum(x == ["-lsusb"] for x in calls), 2)

    def test_uuu_false_success_missing_steps_nonzero_and_timeout_fail_closed(self):
        script = self.root / "task.uuu"
        script.write_text("SDP: dcd -f loader.imx\nFB: Done\n")
        old_env = dict(os.environ)
        try:
            os.environ["CALLS"] = str(self.root / "runner-calls")
            for case in ("hidden_failure", "incomplete", "nonzero", "hang"):
                os.environ["CASE"] = case
                with self.subTest(case=case), self.assertRaises(RuntimeError):
                    flash.run_uuu(str(self.fake), [script.name], self.root,
                                  self.root / "uuu.log", .3 if case == "hang" else 5, script=script)
        finally:
            os.environ.clear()
            os.environ.update(old_env)
        script.unlink()

    def test_bad_checksum_prevents_any_uuu_call(self):
        path = self.package / "zImage"
        original = path.read_bytes()
        try:
            path.write_bytes(original + b"bad")
            status, output, calls = self.cli(dry=True)
            self.assertEqual(status, 1, output.decode())
            self.assertEqual(calls, [])
        finally:
            path.write_bytes(original)

    def test_checksums_reject_traversal_duplicate_and_missing_required_files(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as temp:
            root = Path(temp)
            for manifest in ("0" * 64 + "  ../loader.imx\n",
                             "0" * 64 + "  loader.imx\n" + "0" * 64 + "  loader.imx\n",
                             ""):
                (root / "SHA256SUMS").write_text(manifest)
                with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                    verify_sums(root)

    def test_allocated_zero_skip_rejected_even_when_expansion_and_fsck_pass(self):
        with tempfile.TemporaryDirectory(dir=BUILD) as temp:
            root = Path(temp)
            for name in REQUIRED:
                shutil.copyfile(self.package / name, root / name)
            (root / "rootfs.sparse.img").unlink()
            blocks, allocated = ext4_allocated(self.root / "rootfs.ext4")
            with self.rootfs.path.open("rb") as stream:
                zero = next(c for c in self.rootfs.chunks if c.kind == FILL
                            and self.rootfs.data(stream, c, 0, 4) == bytes(4))
            modified = []
            for a, b in allocated:
                if b <= zero.start or a >= zero.end:
                    modified.append((a, b))
                else:
                    if a < zero.start:
                        modified.append((a, zero.start))
                    if b > zero.end:
                        modified.append((zero.end, b))
            encode_sparse(self.root / "rootfs.ext4", root / "rootfs.sparse.img", blocks, modified)
            check = root / "check"
            check.mkdir()
            with self.assertRaisesRegex(ValueError, "已分配块被错误跳过"):
                preflight_images(root, check, self.config)

    def test_ambiguous_missing_and_wrong_usb_path_rejected(self):
        one = "3:1 MX6ULL SDP: 0x15a2 0x0080 0x0001"
        for output, requested in (("", None), (one + "\n" + one.replace("3:1", "3:2"), None), (one, "3:2")):
            with self.subTest(output=output), self.assertRaises(ValueError):
                flash.select_rom(output, requested)
        self.assertEqual(flash.select_rom(one + "\n" + one.replace("3:1", "3:2"), "3:2"), "3:2")


if __name__ == "__main__":
    BUILD.mkdir(parents=True, exist_ok=True)
    unittest.main()
