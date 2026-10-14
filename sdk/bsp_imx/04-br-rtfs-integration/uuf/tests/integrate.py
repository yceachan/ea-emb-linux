#!/usr/bin/env python3
"""Real firmware/payload packaging and UUU offline checks; never write a board."""
import argparse
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from uuflib import package, model
from uuflib.images import Sparse, command, sha256

parser = argparse.ArgumentParser(description=__doc__)
for name in ('firmware', 'kernel', 'dtb', 'rootfs', 'uuu', 'output'):
    parser.add_argument('--' + name, type=Path, required=True)
parser.add_argument('--linux-boot-device')
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=False)


def call(name, arguments):
    result = subprocess.run([sys.executable, ROOT / 'uuf', *map(str, arguments)],
                            cwd='/tmp', capture_output=True, text=True)
    (out / (name + '.log')).write_text(result.stdout + result.stderr)
    result.check_returncode()
    return result


renamed = out / 'source files'
renamed.mkdir()
shutil.copyfile(args.kernel, renamed / 'application.data')
shutil.copyfile(args.dtb, renamed / 'hardware.data')
call('layout', ['layout', '--kernel', renamed / 'application.data', '--dtb', renamed / 'hardware.data',
                '--rootfs', args.rootfs.resolve(), '--kernel-path', '/zImage', '--dtb-path', '/board.dtb',
                '--output', out / 'layout'])
base = ['pack', '--firmware', args.firmware.resolve(), '--kernel', renamed / 'application.data',
        '--dtb', renamed / 'hardware.data', '--rootfs', args.rootfs.resolve(),
        '--mbr', out / 'layout/mbr.bin', '--targets', out / 'layout/targets.json', '--boot', out / 'layout/boot.json']
if args.linux_boot_device:
    base.extend(['--linux-boot-device', args.linux_boot_device])
call('pack', [*base, '--output', out / 'bundle', '--archive', out / 'system.tar.gz'])
call('unpack', ['unpack', '--archive', out / 'system.tar.gz', '--output', out / 'unpacked'])
call('dry-run', ['deploy', '--archive', out / 'system.tar.gz', '--uuu', args.uuu.absolute(),
                 '--dry-run', '--log-dir', out / 'offline-job'])
old = package.load_bundle(out / 'bundle')
unpacked = package.load_bundle(out / 'unpacked')
if old['manifest'] != unpacked['manifest'] or old['sums'] != unpacked['sums']:
    raise RuntimeError('archive round trip differs')
plan = json.loads((out / 'offline-job/plan.json').read_text())
if not plan['pending_device_checks']:
    raise RuntimeError('offline result hides outstanding device checks')

# Only kernel geometry changes; both filesystem images still must be new.
changed = out / 'changed-layout'
changed.mkdir()
mapping = old['manifest']['targets']
signature = model.parse_mbr(old['mbr'])['signature']
data = model.make_mbr(old['parts'][1]['sectors'] * 512 + 8 * 1024 * 1024,
                      old['parts'][2]['sectors'] * 512, mapping, signature)
(changed / 'mbr.bin').write_bytes(data)
args_changed = list(base)
args_changed[args_changed.index('--mbr') + 1] = changed / 'mbr.bin'
call('layout-rebuild', [*args_changed, '--output', out / 'changed-bundle'])
new = package.load_bundle(out / 'changed-bundle')
for name in ('kernel', 'rtfs'):
    if old['images'][name]['fs']['uuid'] == new['images'][name]['fs']['uuid']:
        raise RuntimeError('old filesystem reused after a layout edit')

# Exercise real fakeroot ownership, hardlinks, absolute symlinks and device nodes.
metadata_tar = out / 'metadata-rootfs.tar'
with tarfile.open(metadata_tar, 'w') as tf:
    directory = tarfile.TarInfo('dev'); directory.type = tarfile.DIRTYPE; directory.mode = 0o755
    tf.addfile(directory)
    file = tarfile.TarInfo('owned'); file.uid = 70000; file.gid = 80000; file.mode = 0o640; file.size = 4
    tf.addfile(file, io.BytesIO(b'data'))
    link = tarfile.TarInfo('alias'); link.type = tarfile.LNKTYPE; link.linkname = 'owned'
    link.uid = 70000; link.gid = 80000; link.mode = 0o640; tf.addfile(link)
    symlink = tarfile.TarInfo('absolute-link'); symlink.type = tarfile.SYMTYPE; symlink.linkname = '/proc/mounts'
    tf.addfile(symlink)
    node = tarfile.TarInfo('dev/test-null'); node.type = tarfile.CHRTYPE; node.devmajor = 1; node.devminor = 3; node.mode = 0o666
    tf.addfile(node)
metadata_args = list(base)
metadata_args[metadata_args.index('--rootfs') + 1] = metadata_tar
if '--linux-boot-device' in metadata_args:
    i = metadata_args.index('--linux-boot-device'); del metadata_args[i:i + 2]
call('rootfs-metadata', [*metadata_args, '--output', out / 'metadata-bundle'])
raw = out / 'metadata.ext4'
Sparse(out / 'metadata-bundle/rtfs.sparse').extract(raw)
owned = command(['debugfs', '-R', 'stat /owned', raw])
alias = command(['debugfs', '-R', 'stat /alias', raw])
if not re.search(r'User:\s+70000\s+Group:\s+80000', owned) or not re.search(r'Mode:\s+0640', owned):
    raise RuntimeError('rootfs ownership or mode changed')
if re.search(r'Inode:\s+(\d+)', owned)[1] != re.search(r'Inode:\s+(\d+)', alias)[1]:
    raise RuntimeError('rootfs hardlink was duplicated')
symlink_stat = command(['debugfs', '-R', 'stat /absolute-link', raw])
node_stat = command(['debugfs', '-R', 'stat /dev/test-null', raw])
if '/proc/mounts' not in symlink_stat or 'character special' not in node_stat:
    raise RuntimeError('rootfs link/device metadata changed')
command(['e2fsck', '-fn', raw])
(out / 'rootfs-metadata.txt').write_text(owned + alias + symlink_stat + node_stat)

# Directory input must preserve the real owner captured before fakeroot.
directory = out / 'directory-rootfs'
directory.mkdir()
(directory / 'owned').write_bytes(b'data')
(directory / 'owned').chmod(0o640)
os.setxattr(directory / 'owned', 'user.uuf_test', b'kept')
os.link(directory / 'owned', directory / 'alias')
os.symlink('/proc/mounts', directory / 'absolute-link')
(directory / 'etc/init.d').mkdir(parents=True)
(directory / 'etc/init.d/rcS').write_text('echo "[BOOT READY]"\n')
fstab_source = '# existing mounts\n/dev/data /data ext4 defaults 0 2\n/dev/old /boot ext4 defaults 0 2\n/dev/swap none swap sw 0 0'
(directory / 'etc/fstab').write_text(fstab_source)
directory_args = list(metadata_args)
directory_args[directory_args.index('--rootfs') + 1] = directory
boot_device = f"/dev/mmcblk1p{mapping['kernel']['partition']}"
directory_args.extend(['--linux-boot-device', boot_device])
call('directory-metadata', [*directory_args, '--output', out / 'directory-bundle'])
directory_raw = out / 'directory.ext4'
Sparse(out / 'directory-bundle/rtfs.sparse').extract(directory_raw)
directory_owned = command(['debugfs', '-R', 'stat /owned', directory_raw])
directory_alias = command(['debugfs', '-R', 'stat /alias', directory_raw])
xattrs = command(['debugfs', '-R', 'ea_list /owned', directory_raw])
fstab_dump = out / 'directory-fstab.txt'
command(['debugfs', '-R', f'dump /etc/fstab {fstab_dump}', directory_raw])
if fstab_dump.read_text() != ('# existing mounts\n/dev/data /data ext4 defaults 0 2\n'
                               f'/dev/swap none swap sw 0 0\n{boot_device} /boot ext4 defaults 0 2\n'):
    raise RuntimeError('/boot preparation removed unrelated fstab entries')
source_stat = (directory / 'owned').stat()
if not re.search(rf'User:\s+{source_stat.st_uid}\s+Group:\s+{source_stat.st_gid}', directory_owned):
    raise RuntimeError('directory input ownership changed inside fakeroot')
if not re.search(r'Mode:\s+0640', directory_owned) or 'user.uuf_test' not in xattrs or 'kept' not in xattrs:
    raise RuntimeError('directory mode or extended attribute changed')
if re.search(r'Inode:\s+(\d+)', directory_owned)[1] != re.search(r'Inode:\s+(\d+)', directory_alias)[1]:
    raise RuntimeError('directory hardlink was duplicated')
command(['e2fsck', '-fn', directory_raw])
(out / 'directory-metadata.txt').write_text(directory_owned + directory_alias + xattrs)

environment = dict(os.environ, UUF_TEST_BUNDLE=str(out / 'bundle'), UUF_TEST_ARCHIVE=str(out / 'system.tar.gz'))
tests = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', ROOT / 'tests', '-v'],
                       check=True, capture_output=True, text=True, env=environment)
(out / 'host-tests.log').write_text(tests.stdout + tests.stderr)
result = {'hardware_access': False, 'complete_sdk_build_in_this_runner': False,
          'firmware_release': str(args.firmware.resolve()),
          'inputs': {name: {'path': str(path.resolve()), 'bytes': path.stat().st_size, 'sha256': sha256(path)}
                     for name, path in (('kernel', args.kernel), ('dtb', args.dtb), ('rootfs', args.rootfs))},
          'archive_direct_dry_run': 'passed', 'archive_round_trip': 'passed',
          'source_names_do_not_define_targets': True,
          'both_filesystems_rebuilt': {name: {'old_uuid': old['images'][name]['fs']['uuid'],
                                            'new_uuid': new['images'][name]['fs']['uuid']}
                                       for name in ('kernel', 'rtfs')},
          'rootfs_metadata': {'uid': 70000, 'gid': 80000, 'mode': '0640', 'hardlink': 'preserved',
                             'absolute_symlink': 'preserved', 'character_device': 'preserved'},
          'directory_metadata': {'uid': source_stat.st_uid, 'gid': source_stat.st_gid,
                                 'mode': '0640', 'hardlink': 'preserved', 'user_xattr': 'preserved'},
          'fstab_boot_preparation': 'replaced only /boot; preserved comments, /data and swap entries',
          'offline_plan': [{'kind': w['kind'], 'source_bytes': w.get('source_bytes'),
                            'logical_bytes': w.get('logical_bytes'), 'partition_bytes': w.get('partition_bytes'),
                            'write_bytes': w['write_bytes']} for w in plan['writes']],
          'host_tests': 'passed; see host-tests.log',
          'linux_boot_device': {'value': args.linux_boot_device,
                                'board_validation': 'pending; integration input is not a device observation'},
          'cold_boot': 'pending-developer-validation'}
(out / 'collection.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'result': str(out / 'collection.json'), 'status': 'passed', 'hardware_access': False}))
