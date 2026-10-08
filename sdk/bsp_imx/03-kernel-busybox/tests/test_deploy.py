"""Deployment gates use mock host commands; no board is accessed."""
import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile
import unittest

BSP = Path(__file__).resolve().parents[1]


class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        shutil.copyfile(BSP / 'deploy.sh', self.base / 'deploy.sh')
        work = self.base / 'artifacts/emmc-rootfs'
        work.mkdir(parents=True)
        shutil.copyfile(BSP / 'emmc-rootfs.uuu', work / 'emmc-rootfs.uuu')
        (work / 'SHA256SUMS').touch()
        with (work / 'rootfs.ext4').open('wb') as image:
            image.truncate(1073741824)
        commands = self.base / 'bin'
        commands.mkdir()
        for name in ['sha256sum', 'e2fsck']:
            command = commands / name
            command.write_text('#!/bin/sh\nexit 0\n')
            command.chmod(0o755)
        uuu = commands / 'uuu'
        uuu.write_text('''#!/usr/bin/env python3
from pathlib import Path
import os, sys
if not sys.stdout.isatty():
    print('Error: UUU must have a PTY for live output')
    sys.exit(1)
with Path(os.environ['TEST_TRACE']).open('a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
if os.environ.get('TEST_UUU_ERROR'):
    print('Error: simulated failure despite exit zero')
    sys.exit(0)
commands = [line for line in Path('emmc-rootfs.uuu').read_text().splitlines()
            if line.startswith('FB:')]
if '-dry' in sys.argv:
    print('\\n'.join(commands))
else:
    if os.environ.get('TEST_INCOMPLETE_FLASH'):
        commands = commands[:-1]
    for line in commands:
        print('Start Cmd:' + line + '\\nOkay')
''')
        uuu.chmod(0o755)
        self.trace = self.base / 'trace'
        self.env = {**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                    'TEST_TRACE': str(self.trace)}

    def tearDown(self):
        self.temp.cleanup()

    def run_script(self, args=(), answer=None, **settings):
        command = ['bash', str(self.base / 'deploy.sh'), *args]
        env = {**self.env, **settings}
        if answer is None:
            return subprocess.run(command, input='', capture_output=True, text=True,
                                  env=env, timeout=10)
        master, slave = pty.openpty()
        try:
            process = subprocess.Popen(command, stdin=slave, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True, env=env)
            os.write(master, (answer + '\n').encode())
            stdout, stderr = process.communicate(timeout=10)
            return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
        finally:
            os.close(master)
            os.close(slave)

    def test_dry_run_never_flashes(self):
        result = self.run_script(['--dry-run'])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace.read_text(), '-dry emmc-rootfs.uuu\n')

    def test_zero_exit_uuu_error_stops_before_confirmation(self):
        result = self.run_script(answer='', TEST_UUU_ERROR='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.trace.read_text(), '-dry emmc-rootfs.uuu\n')

    def test_noninteractive_run_cannot_flash(self):
        result = self.run_script()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.trace.read_text(), '-dry emmc-rootfs.uuu\n')

    def test_cancel_after_preflight_never_flashes(self):
        result = self.run_script(answer='cancel')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace.read_text(), '-dry emmc-rootfs.uuu\n')

    def test_confirmation_flashes_only_after_preflight(self):
        result = self.run_script(answer='')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.trace.read_text(),
                         '-dry emmc-rootfs.uuu\n-v -t 30 emmc-rootfs.uuu\n')

    def test_incomplete_flash_record_is_failure(self):
        result = self.run_script(answer='', TEST_INCOMPLETE_FLASH='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('UUU 写入命令全部成功', result.stdout)


if __name__ == '__main__':
    unittest.main()
