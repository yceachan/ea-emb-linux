"""Host and protocol checks against a real prepared bundle; no board access."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import struct
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uuflib import backend, cli, model, package, transport
from uuflib.images import Sparse, BLOCK, RAW, FILL, SKIP


class Board:
    """Only the host wire protocol is emulated; it never opens a device."""
    def __init__(self, bundle):
        self.mbr = bundle['mbr']
        self.conf = bundle['paths']['boot_config'].read_bytes()
        sp = Sparse(bundle['paths']['kernel_sparse'])
        with sp.path.open('rb') as f:
            self.sb = sp.data(f, sp.chunks[0], 1024, 1024)
        self.cid = '0123456789abcdef0123456789abcdef'
        self.user = 7634944
        self.partconf = 0x48
        self.erased = 0xff
        self.erase = 2048
        self.boot = 8192
        self.export = b''
        self.calls, self.writes = [], []
        self.fw_result = 'skipped'
        self.fail = None
        self.before_write = None

    def value(self, key):
        values = {'abi': '1', 'cid': self.cid, 'user': f'{self.user:x}',
                  'boot': f'{self.boot:x}', 'erase': f'{self.erase:x}',
                  'erased': f'{self.erased:x}', 'partconf': f'{self.partconf:x}',
                  'kernel-part': '1', 'size': f'{len(self.export):x}', 'fw-result': self.fw_result}
        if key.startswith('data'):
            i = int(key[4:]) * 24
            return self.export[i:i + 24].hex()
        return values[key]

    def run(self, uuu, options, work, logfile, timeout, emit, *, script=None, dry=False):
        self.calls.append(list(options))
        if '-lsusb' in options:
            return '1:2 MX6ULL SDP: 0x15a2 0x0080\n'
        lines = [l for l in Path(script).read_text().splitlines()
                 if re.match(r'^(SDP|FB)(?:\[-t [0-9]+\])?:', l)]
        if dry:
            return '\n'.join(lines) + '\n'
        if Path(script).name == 'write-verify.uuu' and self.before_write:
            self.before_write()
        text = ''
        for line in lines:
            command = re.sub(r'^FB(?:\[-t [0-9]+\])?: ', '', line)
            if self.fail and self.fail in command:
                raise RuntimeError('emulated UUU failure')
            if command.startswith('ucmd uuf export '):
                fields = command.split()
                self.export = self.mbr if int(fields[-2], 16) == 0 else self.sb
            elif command.startswith('ucmd uuf exportfile '):
                self.export = self.conf
            elif command.startswith('ucmd uuf locate '):
                if int(command.split()[-1], 16) not in (0, 1):
                    raise RuntimeError('emulated locator rejected')
            elif command.startswith('ucmd uuf file '):
                size, digest = command.split()[-2:]
                if len(self.conf) != int(size, 16) or hashlib.sha256(self.conf).hexdigest() != digest:
                    raise RuntimeError('emulated extlinux identity changed')
            elif command.startswith('ucmd mmc write '):
                self.mbr = (Path(work) / 'mbr.bin').read_bytes()
                self.writes.append(command)
            elif command.startswith('flash '):
                self.writes.append(command)
                if command.endswith('kernel.sparse'):
                    sp = Sparse(Path(work) / 'kernel.sparse')
                    with sp.path.open('rb') as f:
                        self.sb = sp.data(f, sp.chunks[0], 1024, 1024)
                    self.conf = (Path(work) / 'extlinux.conf').read_bytes()
            elif command.startswith(('ucmd uuf fw ', 'ucmd uuf writefile ', 'ucmd uuf erase ')):
                self.writes.append(command)
            elif command.startswith('ucmd uuf bootconf '):
                ack, part = [int(x, 16) for x in command.split()[-2:]]
                self.partconf = ack << 6 | part << 3
            value = self.value(command.removeprefix('getvar uuf-')) if command.startswith('getvar uuf-') else ''
            text += f'Start Cmd:{line}\n{value}1:2>Okay (0.001s)\n'
        Path(logfile).write_text(text)
        if not transport.complete(text, script):
            raise AssertionError('emulated transcript does not match generated script')
        return text


class Host(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.environ.get('UUF_TEST_BUNDLE'):
            raise RuntimeError('Set UUF_TEST_BUNDLE to a real M2 pack output; see README')
        cls.bundle_path = Path(os.environ['UUF_TEST_BUNDLE']).resolve()
        cls.bundle = package.load_bundle(cls.bundle_path)
        cls.archive = Path(os.environ['UUF_TEST_ARCHIVE']).resolve()
        cls.firmware = cls.bundle['paths']['uboot'].parent
        cls.base = tempfile.TemporaryDirectory(prefix='m2-tests-')
        cls.root = Path(cls.base.name)
        cls.targets = cls.root / 'targets.json'
        cls.targets.write_text(json.dumps(cls.bundle['manifest']['targets']))

    @classmethod
    def tearDownClass(cls):
        cls.base.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root))
        self.events, self.confirmations = [], []

    def test_kernel_component_accepts_32m_boundary_and_rejects_one_byte_more(self):
        source = self.work / 'size-fixture.bin'
        with source.open('wb') as stream:
            header = bytearray(40)
            struct.pack_into('<I', header, 36, 0x016f2818)
            stream.write(header)
            stream.truncate(32 * 1024 ** 2)
        self.assertEqual(package.component('kernel', source)['bytes'], 32 * 1024 ** 2)
        with source.open('ab') as stream:
            stream.write(b'x')
        with self.assertRaisesRegex(ValueError, '32 MiB'):
            package.component('kernel', source)

    def request(self, args):
        r = vars(cli.parser().parse_args(args))
        r.update(uuu='/usr/bin/true', log_dir=str(self.work / 'job'))
        return r

    def execute(self, r, board=None, confirm=None):
        board = board or Board(self.bundle)
        def confirmation(phase, plan):
            self.confirmations.append(phase)
            if confirm:
                confirm(phase, plan, board)
        with patch('uuflib.backend.transport.run', side_effect=board.run):
            result = backend.Session(r, lambda k, d: self.events.append((k, d)), confirmation).execute()
        return result, board

    def test_archive_direct_deploy_has_mbr_capacity_not_container_length(self):
        r = self.request(['deploy', '--archive', str(self.archive), '--dry-run'])
        plan, board = self.execute(r)
        self.assertTrue(all(c[0] == '-dry' for c in board.calls))
        self.assertEqual(self.confirmations, [])
        self.assertNotIn('profile', plan)
        self.assertTrue(plan['pending_device_checks'])
        for w in plan['writes']:
            if w['kind'].endswith('-partition'):
                self.assertEqual(w['partition_bytes'], w['logical_bytes'])
                self.assertGreater(w['partition_bytes'], w['source_bytes'])
                self.assertLessEqual(w['write_bytes'], w['logical_bytes'])

    def test_full_deploy_blank_disk_and_larger_device_keep_archive_geometry(self):
        board = Board(self.bundle)
        board.mbr = bytes(512)
        board.user *= 2
        r = self.request(['deploy', '--archive', str(self.archive)])
        result, board = self.execute(r, board)
        self.assertEqual(result['state'], 'written-and-verified')
        self.assertEqual(board.mbr, self.bundle['mbr'])
        self.assertEqual(self.confirmations, ['host-plan', 'target-write'])

    def test_small_device_rejected_before_any_persistent_write(self):
        board = Board(self.bundle)
        board.user = 10000
        with self.assertRaisesRegex(ValueError, '容量'):
            self.execute(self.request(['deploy', '--archive', str(self.archive)]), board)
        self.assertEqual(board.writes, [])

    def test_only_mapped_kernel_partition_may_be_active(self):
        data = bytearray(self.bundle['mbr'])
        data[446 + (self.bundle['manifest']['targets']['rtfs']['partition'] - 1) * 16] = 0x80
        with self.assertRaisesRegex(ValueError, '活动分区'):
            model.geometry(bytes(data), self.bundle['manifest']['targets'])

    def test_extlinux_change_at_write_script_stops_before_every_write(self):
        board = Board(self.bundle)
        board.before_write = lambda: setattr(board, 'conf', board.conf.replace(b'  APPEND ', b'  APPEND quiet '))
        request = self.request(['update', '--firmware', str(self.firmware), '--targets', str(self.targets),
                                '--uboot', '--kernel', str(self.bundle['paths']['kernel'])])
        with self.assertRaisesRegex(RuntimeError, 'extlinux identity changed'):
            self.execute(request, board)
        self.assertEqual(self.confirmations, ['host-plan', 'target-write'])
        self.assertEqual(board.writes, [])
        script = (self.work / 'job/write-verify.uuu').read_text()
        self.assertLess(script.index('uuf file '), script.index('uuf fw '))

    def test_inspect_empty_disk_returns_basic_info_without_locator(self):
        board = Board(self.bundle)
        board.mbr = bytes(512)
        result, board = self.execute(self.request(['inspect', '--firmware', str(self.firmware)]), board)
        self.assertFalse(result['mbr_valid'])
        self.assertEqual(result['mbr_entries'], [])
        self.assertEqual(board.writes, [])
        self.assertEqual(self.confirmations, ['host-plan'])
        self.assertNotIn('locate', ''.join(p.read_text() for p in (self.work / 'job').glob('*.uuu')))

    def test_firmware_only_needs_no_layout_on_empty_disk(self):
        board = Board(self.bundle)
        board.mbr = bytes(512)
        result, board = self.execute(self.request(['update', '--firmware', str(self.firmware), '--uboot']), board)
        self.assertEqual(result['firmware'], 'skipped')
        self.assertTrue(all('uuf fw' in w for w in board.writes))
        self.assertEqual(board.mbr, bytes(512))

    def test_kernel_dtb_combination_preserves_boot_config_and_uses_target_paths(self):
        r = self.request(['update', '--firmware', str(self.firmware), '--targets', str(self.targets),
                          '--kernel', str(self.bundle['paths']['kernel']), '--dtb', str(self.bundle['paths']['dtb'])])
        board = Board(self.bundle)
        board.conf = board.conf.replace(b'  APPEND ', b'  APPEND quiet ')
        result, board = self.execute(r, board)
        text = (self.work / 'job/write-verify.uuu').read_text()
        self.assertIn('uuf filesave', text)
        self.assertIn('/extlinux/extlinux.conf', text)
        self.assertNotIn('mmc write', text)
        self.assertEqual(len(board.writes), 2)
        self.assertTrue(all('uuf writefile' in w for w in board.writes))
        self.assertEqual(result['plan']['targets'], self.bundle['manifest']['targets'])
        self.assertIn(b'APPEND quiet ', board.conf)

    def test_expected_mbr_change_rejected_before_persistent_write(self):
        expected = self.work / 'expected-mbr.bin'
        expected.write_bytes(self.bundle['mbr'])
        board = Board(self.bundle)
        data = bytearray(board.mbr); data[10] ^= 1; board.mbr = bytes(data)
        with self.assertRaisesRegex(ValueError, '预期快照'):
            self.execute(self.request(['update', '--firmware', str(self.firmware), '--uboot',
                                       '--expected-mbr', str(expected)]), board)
        self.assertEqual(board.writes, [])

    def test_invalid_timeout_is_a_single_rpc_error(self):
        request = {'operation': 'inspect', 'firmware': str(self.firmware), 'timeout': 'nan'}
        result = subprocess.run([sys.executable, ROOT / 'uuf', 'rpc'], input=json.dumps(request) + '\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual([json.loads(x)['event'] for x in result.stdout.splitlines()], ['error'])

    def test_swapped_component_roles_cannot_erase_real_rtfs(self):
        v = copy.deepcopy(self.bundle['manifest']['targets'])
        v['kernel']['partition'], v['dtb']['partition'], v['rtfs']['partition'] = 2, 2, 1
        path = self.work / 'swapped.json'
        path.write_text(json.dumps(v))
        board = Board(self.bundle)
        with self.assertRaisesRegex(ValueError, '角色'):
            self.execute(self.request(['erase', '--firmware', str(self.firmware), '--targets', str(path), '--region', 'kernel']), board)
        self.assertEqual(board.writes, [])

    def test_rtfs_update_uses_existing_mbr_and_rejects_capacity_mismatch(self):
        board = Board(self.bundle)
        data = bytearray(board.mbr)
        import struct
        struct.pack_into('<I', data, 446 + 16 + 12, self.bundle['parts'][2]['sectors'] + 8)
        board.mbr = bytes(data)
        r = self.request(['update', '--firmware', str(self.firmware), '--targets', str(self.targets),
                          '--rtfs', str(self.bundle['paths']['rtfs_sparse'])])
        with self.assertRaisesRegex(ValueError, '逻辑长度'):
            self.execute(r, board)
        self.assertEqual(board.writes, [])

    def test_confirmation_reprobe_rejects_changed_cid(self):
        board = Board(self.bundle)
        def change(phase, plan, b):
            if phase == 'target-write':
                b.cid = 'f' * 32
        with self.assertRaisesRegex(ValueError, '确认期间'):
            self.execute(self.request(['update', '--firmware', str(self.firmware), '--uboot']), board, change)
        self.assertEqual(board.writes, [])

    def test_staged_input_change_after_confirmation_rejected(self):
        board = Board(self.bundle)
        def change(phase, plan, b):
            if phase == 'target-write':
                Path(plan['inputs']['loader.imx']['path']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, '暂存输入'):
            self.execute(self.request(['update', '--firmware', str(self.firmware), '--uboot']), board, change)
        self.assertEqual(board.writes, [])

    def test_file_probe_failure_stops_before_target_write_confirmation(self):
        board = Board(self.bundle)
        board.fail = 'uuf writable'
        with self.assertRaises(RuntimeError):
            self.execute(self.request(['update', '--firmware', str(self.firmware), '--targets', str(self.targets),
                                       '--kernel', str(self.bundle['paths']['kernel'])]), board)
        self.assertEqual(self.confirmations, ['host-plan'])
        self.assertEqual(board.writes, [])

    def test_explicit_erase_never_expands_alignment(self):
        board = Board(self.bundle)
        r = self.request(['erase', '--firmware', str(self.firmware), '--region', 'firmware', '--offset', '1024', '--bytes', '512'])
        with self.assertRaisesRegex(ValueError, '擦除粒度'):
            self.execute(r, board)
        self.assertEqual(board.writes, [])

    def test_large_partition_erase_splits_native_length_without_changing_range(self):
        board = Board(self.bundle)
        data = bytearray(board.mbr)
        number = self.bundle['manifest']['targets']['rtfs']['partition']
        size = 5 * 1024 ** 3
        struct.pack_into('<I', data, 446 + (number - 1) * 16 + 12, size // 512)
        board.mbr = bytes(data)
        part = model.geometry(board.mbr, self.bundle['manifest']['targets'])[1][number]
        board.user = part['start'] + part['sectors'] + 2048
        result, board = self.execute(self.request(['erase', '--firmware', str(self.firmware),
                                                  '--targets', str(self.targets), '--region', 'rtfs']), board)
        self.assertEqual(result['plan']['writes'][0]['write_bytes'], size)
        cursor = part['start']
        grain = board.erase * 512
        self.assertGreater(len(board.writes), 1)
        for line in board.writes:
            hw, start, length = [int(x, 16) for x in line.split()[-3:]]
            self.assertEqual(hw, 0)
            self.assertEqual(start, cursor)
            self.assertLessEqual(length, 0xffffffff)
            self.assertEqual(start * 512 % grain, 0)
            self.assertEqual(length % grain, 0)
            cursor += length // 512
        self.assertEqual(cursor, part['start'] + part['sectors'])

    def test_persistent_error_stops_host_postwrite_operations(self):
        board = Board(self.bundle)
        board.fail = 'uuf fw '
        with self.assertRaises(RuntimeError):
            self.execute(self.request(['update', '--firmware', str(self.firmware), '--uboot']), board)
        self.assertFalse(any(k == 'result' and d.get('state') == 'written-and-verified' for k, d in self.events))

    def test_archive_link_and_traversal_rejected(self):
        for kind in ('traversal', 'link'):
            source = self.work / (kind + '.tar')
            with tarfile.open(source, 'w') as tf:
                m = tarfile.TarInfo('../escape' if kind == 'traversal' else 'link')
                if kind == 'link':
                    m.type = tarfile.SYMTYPE
                    m.linkname = '/etc/passwd'
                else:
                    m.size = 1
                tf.addfile(m, io.BytesIO(b'x') if kind == 'traversal' else None)
            with self.assertRaises(ValueError):
                package.unpack(source, self.work / ('out-' + kind))
        with self.assertRaisesRegex(ValueError, '内部'):
            package.archive(self.bundle_path, self.bundle_path / 'self.tar.gz')

    def test_pack_rejects_output_inside_input_trees_before_creating_files(self):
        source = self.work / 'source-rootfs'
        source.mkdir()
        for parent in (source, self.firmware):
            with self.subTest(parent=parent):
                output = parent / 'nested-pack-output'
                with self.assertRaisesRegex(ValueError, '输入目录内部'):
                    package.pack({'rootfs': str(source), 'firmware': str(self.firmware), 'output': str(output)})
                self.assertFalse(output.exists())
            with self.subTest(archive_parent=parent):
                output = self.work / 'clean-output'
                archive = parent / 'nested-pack-archive.tar.gz'
                with self.assertRaisesRegex(ValueError, '输入目录内部'):
                    package.pack({'rootfs': str(source), 'firmware': str(self.firmware),
                                  'output': str(output), 'archive': str(archive)})
                self.assertFalse(output.exists())
                self.assertFalse(archive.exists())
        output = self.work / 'clean-output'
        with self.assertRaisesRegex(ValueError, '待归档目录内部'):
            package.pack({'rootfs': str(source), 'firmware': str(self.firmware),
                          'output': str(output), 'archive': str(output / 'system.tar.gz')})
        self.assertFalse(output.exists())

    def test_layout_rejects_output_inside_rootfs_before_creating_files(self):
        source = self.work / 'source-rootfs'
        source.mkdir()
        output = source / 'layout'
        with self.assertRaisesRegex(ValueError, '输入目录内部'):
            cli.create_layout({'rootfs': str(source), 'output': str(output)})
        self.assertFalse(output.exists())

    def test_rpc_does_not_ignore_false_component_choice_for_full_deploy(self):
        request = {'operation': 'deploy', 'archive': str(self.archive), 'uboot': False}
        result = subprocess.run([sys.executable, ROOT / 'uuf', 'rpc'], input=json.dumps(request) + '\n', text=True, capture_output=True)
        self.assertEqual(result.returncode, 1)
        events = [json.loads(l) for l in result.stdout.splitlines()]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['event'], 'error')

    def test_transport_requires_all_command_successes_even_with_zero_status(self):
        script = self.work / 'test.uuu'
        script.write_text('FB: ucmd uuf info\nFB: Done\n')
        self.assertFalse(transport.complete('Start Cmd:FB: ucmd uuf info\n1:2>Okay (0s)\n', script))
        fake = self.work / 'bad-uuu'
        fake.write_text('#!/bin/sh\necho "Error emulated"\nexit 0\n')
        fake.chmod(0o755)
        with self.assertRaises(RuntimeError):
            transport.run(fake, [], self.work, self.work / 'bad.log', 2, lambda *x: None)

    def test_relative_uuu_argument_environment_and_path_preserve_launcher(self):
        launchers = self.work / 'launchers'
        launchers.mkdir()
        runner = self.work / 'runner'
        runner.write_text(f'#!{sys.executable}\nimport sys\nfrom pathlib import Path\nprint(Path(sys.argv[-1]).read_text())\n')
        runner.chmod(0o755)
        launcher = launchers / 'uuu'
        launcher.symlink_to(runner)
        previous = Path.cwd()
        try:
            os.chdir(self.work)
            for source in ('argument', 'environment', 'path'):
                with self.subTest(source=source):
                    r = self.request(['inspect', '--firmware', str(self.firmware), '--dry-run'])
                    r['log_dir'] = str(self.work / ('relative-' + source))
                    r['uuu'] = './launchers/uuu' if source == 'argument' else None if source == 'environment' else 'uuu'
                    environment = {'UUF_UUU': './launchers/uuu', 'PATH': './launchers:' + os.environ['PATH']}
                    with patch.dict(os.environ, environment):
                        session = backend.Session(r, lambda *args: None, lambda *args: self.fail('unexpected confirmation'))
                        self.assertEqual(session.uuu, str(launcher))
                        session.execute()
        finally:
            os.chdir(previous)

    def test_successful_command_echo_with_error_filename_is_not_a_failure(self):
        script = self.work / 'test.uuu'
        script.write_text('FB: ucmd uuf writable 1 /Error.bin\nFB: Done\n')
        fake = self.work / 'echo-uuu'
        fake.write_text(f'''#!{sys.executable}
import sys
from pathlib import Path
lines = Path(sys.argv[-1]).read_text().splitlines()
for line in lines:
    print(line if '-dry' in sys.argv else 'Start Cmd:' + line + '\\n1:2>Okay (0s)')
''')
        fake.chmod(0o755)
        for dry in (True, False):
            with self.subTest(dry=dry):
                transport.run(fake, ['-dry' if dry else '-v', script.name], self.work,
                              self.work / f'echo-{dry}.log', 2, lambda *args: None, script=script, dry=dry)

    def test_repeated_cancel_cleans_entire_uuu_process_group(self):
        fake = self.work / 'slow-uuu'
        pidfile = self.work / 'grandchild.pid'
        fake.write_text('''#!/usr/bin/env python3
import os,sys,signal,time
from pathlib import Path
if '-dry' in sys.argv:
    print(Path(sys.argv[-1]).read_text());sys.exit(0)
if '-lsusb' in sys.argv:
    print('1:2 MX6ULL SDP: 0x15a2 0x0080');sys.exit(0)
if os.fork()==0:
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    Path(os.environ['TEST_GRANDCHILD_PID']).write_text(str(os.getpid()))
    while True:time.sleep(1)
while True:time.sleep(1)
''')
        fake.chmod(0o755)
        request = {'operation': 'inspect', 'firmware': str(self.firmware), 'uuu': str(fake),
                   'log_dir': str(self.work / 'cancel-job')}
        process = subprocess.Popen([sys.executable, ROOT / 'uuf', 'rpc'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   env=dict(os.environ, TEST_GRANDCHILD_PID=str(pidfile)))
        try:
            process.stdin.write(json.dumps(request) + '\n'); process.stdin.flush()
            for line in process.stdout:
                event = json.loads(line)
                if event['event'] == 'confirmation':
                    process.stdin.write(json.dumps({'confirm': event['data']['token']}) + '\n')
                    process.stdin.flush()
                    break
            deadline = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(pidfile.exists())
            os.kill(process.pid, signal.SIGINT)
            time.sleep(.03)
            if process.poll() is None:
                os.kill(process.pid, signal.SIGINT)
            process.communicate(timeout=5)
            self.assertEqual(process.returncode, 130)
            state = Path('/proc') / pidfile.read_text() / 'status'
            self.assertTrue(not state.exists() or '\nState:\tZ' in state.read_text())
        finally:
            if process.poll() is None:
                process.kill(); process.wait()


if __name__ == '__main__':
    unittest.main()
