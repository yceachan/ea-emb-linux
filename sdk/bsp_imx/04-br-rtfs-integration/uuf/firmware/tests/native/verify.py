#!/usr/bin/env python3
"""Verify actual U-Boot ext4 code against real payloads on host-only media."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import struct
import os
import sys


def command(argv):
    result = subprocess.run([str(x) for x in argv], check=True,
                            capture_output=True, text=True, env=dict(os.environ, LC_ALL='C'))
    return result.stdout


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def component(kind, path):
    size = path.stat().st_size
    if not 40 <= size <= 32 * 1024 * 1024:
        raise ValueError(f'{kind}: input exceeds the 32 MiB fastboot buffer or is truncated')
    with path.open('rb') as stream:
        head = stream.read(40)
    if kind == 'kernel':
        if head[36:40] != struct.pack('<I', 0x016f2818):
            raise ValueError('kernel input must be an ARM zImage')
    else:
        if head[:4] != b'\xd0\x0d\xfe\xed' or struct.unpack_from('>I', head, 4)[0] != size:
            raise ValueError('DTB header or size is invalid')
        command(['dtc', '-I', 'dtb', '-O', 'dts', '-o', os.devnull, path])
        if '100ask,imx6ull-pro' not in command(['fdtget', '-t', 's', path, '/', 'compatible']).split():
            raise ValueError('DTB is not for this board')


def make_ext4(tree, output):
    with output.open('xb') as stream:
        stream.truncate(128 * 1024 * 1024)
    command(['mkfs.ext4', '-q', '-F', '-b', '4096', '-I', '256', '-m', '0',
             '-O', 'has_journal,extent,filetype,sparse_super,large_file,^metadata_csum,^64bit,^orphan_file,^dir_index,^flex_bg',
             '-E', 'lazy_itable_init=0,lazy_journal_init=0,no_copy_xattrs',
             '-L', 'kernel', '-d', tree, output])
    command(['e2fsck', '-fn', output])

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True, help='配置后的固定 U-Boot 源码快照')
p.add_argument('--kernel', type=Path, required=True)
p.add_argument('--dtb', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
a.output.mkdir(parents=True, exist_ok=False)
component('kernel', a.kernel); component('dtb', a.dtb)
subprocess.run([sys.executable, Path(__file__).with_name('build.py'), a.source, a.output / 'native'], check=True)
tree = a.output / 'tree'
tree.mkdir(); (tree / 'extlinux').mkdir()
(tree / 'kernel').write_bytes(b'previous kernel')
(tree / 'dtb').write_bytes(b'previous dtb')
(tree / 'extra').write_bytes(b'unselected extra file')
(tree / 'extlinux/extlinux.conf').write_text('DEFAULT unchanged\n')
raw = a.output / 'baseline.ext4'
make_ext4(tree, raw)
# Include high UID/GID values: selected file ownership must survive unlink/create.
for field, value in (('mode', '0100640'), ('uid', '70000'), ('gid', '80000')):
    command(['debugfs', '-w', '-R', f'set_inode_field /kernel {field} {value}', raw])
command(['debugfs', '-w', '-R', 'ea_set / user.uuf-parent preserved', raw])
parent_attribute = command(['debugfs', '-R', 'ea_get / user.uuf-parent', raw])
original_extra = command(['debugfs', '-R', 'stat /extra', raw])
exe = a.output / 'native/ext4-test'
records = []
text = command([exe, raw, '/kernel', a.kernel, 'fs-devread-short'])
assert 'fs_devread=0 reads=1' in text
records.append({'fault': 'fs_devread short small-read', 'result': text.strip()})
text = command([exe, raw, '/kernel', a.kernel, 'writable-success'])
assert 'writes=0' in text
for case, target, commands in (
    ('inline-xattr', '/kernel', ['ea_set /kernel user.uuf selected']),
    ('external-xattr', '/kernel', ['ea_set /kernel user.uuf ' + 'x' * 512]),
    ('hardlink', '/kernel', ['link /kernel /alias', 'set_inode_field /kernel links_count 2']),
    ('symlink', '/alias', ['symlink /alias /kernel']),
    ('immutable', '/kernel', ['set_inode_field /kernel flags 0x80010']),
    ('extent-index', '/kernel', [f'fallocate /kernel {n} {n}' for n in (20, 40, 60, 80, 100)]),
    ('unclean-journal', '/kernel', ['set_super_value feature_incompat 0x46']),
    ('missing-journal', '/kernel', ['set_super_value feature_compat 0']),
    ('unsupported-feature', '/kernel', ['set_super_value feature_incompat 0x442']),
):
    media = a.output / (case + '.ext4')
    subprocess.run(['cp', '--reflink=auto', raw, media], check=True)
    for cmd in commands:
        command(['debugfs', '-w', '-R', cmd, media])
    if case == 'extent-index':
        assert '(ETB0)' in command(['debugfs', '-R', 'stat /kernel', media])
    before = sha256(media)
    text = command([exe, media, target, a.kernel, 'writable-reject'])
    assert 'writes=0' in text and sha256(media) == before
    records.append({'readonly_rejected': case, 'result': text.strip()})
for target, source in (('/kernel', a.kernel), ('/dtb', a.dtb)):
    text = command([exe, raw, target, source, 'success'])
    assert 'recover=0' in text
    records.append({'target': target, 'source_sha256': sha256(source), 'result': text.strip()})
    extracted = a.output / target.lstrip('/')
    command(['debugfs', '-R', f'dump {target} {extracted}', raw])
    assert sha256(extracted) == sha256(source)
assert command(['debugfs', '-R', 'stat /extra', raw]) == original_extra
assert command(['debugfs', '-R', 'ea_get / user.uuf-parent', raw]) == parent_attribute
for target, expected in (('/extra', b'unselected extra file'), ('/extlinux/extlinux.conf', b'DEFAULT unchanged\n')):
    out = a.output / (Path(target).name + '.kept')
    command(['debugfs', '-R', f'dump {target} {out}', raw])
    assert out.read_bytes() == expected
stat = command(['debugfs', '-R', 'stat /kernel', raw])
assert re.search(r'Mode:\s+0640', stat) and re.search(r'User:\s+70000\s+Group:\s+80000', stat)
command(['e2fsck', '-fn', raw])
boundary = a.output / '32m-boundary.bin'
with boundary.open('wb') as stream:
    pattern = bytes(range(256)) * 4096
    for _ in range(32):
        stream.write(pattern)
text = command([exe, raw, '/kernel', boundary, 'success'])
assert 'written=33554432' in text and 'recover=0' in text
peak = int(re.search(r'peak_heap=(\d+)', text)[1])
extracted = a.output / '32m-extracted.bin'
command(['debugfs', '-R', f'dump /kernel {extracted}', raw])
assert sha256(extracted) == sha256(boundary)
assert command(['debugfs', '-R', 'stat /extra', raw]) == original_extra
assert command(['debugfs', '-R', 'ea_get / user.uuf-parent', raw]) == parent_attribute
stat = command(['debugfs', '-R', 'stat /kernel', raw])
assert re.search(r'Mode:\s+0640', stat) and re.search(r'User:\s+70000\s+Group:\s+80000', stat)
command(['e2fsck', '-fn', raw])
records.append({'boundary_bytes': boundary.stat().st_size, 'peak_heap_bytes': peak,
                'scope': 'deterministic size fixture; not a bootable kernel', 'result': text.strip()})
for mode in ('short-read', 'short-read-4', 'short-read-20', 'short-read-60',
             'short-write', 'short-write-8', 'short-write-20', 'short-write-40'):
    media = a.output / (mode + '.ext4')
    subprocess.run(['cp', '--reflink=auto', raw, media], check=True)
    text = command([exe, media, '/kernel', a.kernel, mode])
    assert 'result=-1 written=0' in text and 'io_error=-5' in text
    records.append({'fault': mode, 'result': text.strip()})
for mode in ('deinit-alloc', 'deinit-inode-read', 'deinit-jsb-read', 'deinit-write'):
    media = a.output / (mode + '.ext4')
    subprocess.run(['cp', '--reflink=auto', raw, media], check=True)
    text = command([exe, media, '/kernel', a.kernel, mode])
    assert 'result=-1 written=0' in text and 'recover=1' in text
    assert re.search(r'io_error=-\d+', text)
    assert re.search(r'writes=[1-9]\d*', text)
    if mode == 'deinit-jsb-read':
        assert 'fault=journal-superblock-data-read' in text
    records.append({'fault': mode, 'recover_preserved': True, 'result': text.strip()})
result = {'hardware_access': False, 'complete_sdk_build': False, 'kernel_bytes': a.kernel.stat().st_size,
          'dtb_bytes': a.dtb.stat().st_size, 'heap_limit_bytes': 16 * 1024 * 1024,
          'download_limit_bytes': 32 * 1024 * 1024, 'boundary_peak_heap_bytes': peak,
          'selected_mode_uid_gid': '0640 / 70000 / 80000', 'unselected_file_data_and_inode_preserved': True,
          'extlinux_preserved': True, 'parent_inline_xattr_preserved': True,
          'fs_devread_small_short_io_rejected': True, 'deinit_faults_preserve_recover': True,
          'journal_superblock_data_read_fault_covered': True,
          'e2fsck': 'passed', 'records': records}
(a.output / 'collection.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
