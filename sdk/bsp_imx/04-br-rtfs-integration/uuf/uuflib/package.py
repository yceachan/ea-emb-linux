"""Allocation-aware partition images and a data-only, checksummed archive."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import tarfile
import tempfile

from .images import BLOCK, BUFFER, Sparse, command, encode_sparse, ext4_allocated, sha256
from .model import (targets, geometry, firmware_target, json_file,
                    boot_text, parse_boot, boot_root)

ROOT = Path(__file__).resolve().parents[1]


def firmware_inputs():
    root = ROOT / 'firmware'
    names = ['base-revision', 'register-board.patch', 'ext4-io.patch', 'build.sh']
    names += sorted(str(p.relative_to(root)) for p in (root / 'overlay').rglob('*') if p.is_file())
    return ''.join(f'{sha256(root / name)}  {name}\n' for name in names)


def imx(path):
    p = Path(path)
    size = p.stat().st_size
    with p.open('rb') as stream:
        head = stream.read(64)
    if not 4096 <= size <= 0xffc00 or head[:4] != b'\xd1\x00\x20\x40':
        raise ValueError('固件 IVT 或 boot0 保留范围不合法')
    # IVT self and boot_data pointers are target addresses, not host offsets.
    entry, _, dcd, boot, base = struct.unpack_from('<5I', head, 4)
    off = boot - base
    if not 0 <= off <= size - 12 or not base <= entry < base + size:
        raise ValueError('固件 IVT 指针越界')
    with p.open('rb') as stream:
        stream.seek(off)
        start, length, plugin = struct.unpack('<3I', stream.read(12))
    if plugin or length < size or length > 0x200000 or not start <= base < start + length:
        raise ValueError('固件 Boot Data 不合法')
    if not base <= dcd < base + size:
        raise ValueError('固件缺少本板 DDR DCD')
    return size


def validate_firmware(folder):
    folder = Path(folder)
    sums = verify_sums(folder)
    required = {'u-boot-dtb.imx', '.config', 'source-revision', 'bsp-inputs.sha256', 'source-tree.sha256', 'image-info.txt'}
    if not required <= sums.keys():
        raise ValueError('固件输入缺少构建记录')
    if (folder / 'bsp-inputs.sha256').read_text() != firmware_inputs():
        raise ValueError('固件板级输入与当前 uuf 不同；重新 configure/build')
    if (folder / 'source-revision').read_text() != (ROOT / 'firmware/base-revision').read_text():
        raise ValueError('固件 revision 与固定基线不同')
    config = dict(line.split('=', 1) for line in (folder / '.config').read_text().splitlines()
                  if line.startswith('CONFIG_') and '=' in line)
    expected = {'CONFIG_BOOTDELAY': '3', 'CONFIG_ENV_IS_NOWHERE': 'y',
                'CONFIG_BOARD_LATE_INIT': 'y', 'CONFIG_CMD_EXT4_WRITE': 'y',
                'CONFIG_CMD_SYSBOOT': 'y', 'CONFIG_FASTBOOT_UUU_SUPPORT': 'y',
                'CONFIG_FASTBOOT_FLASH_MMC_DEV': '1', 'CONFIG_FASTBOOT_BUF_ADDR': '0x82000000',
                'CONFIG_FASTBOOT_BUF_SIZE': '0x1000000', 'CONFIG_SYS_MALLOC_LEN': '0x1000000'}
    if any(config.get(k) != v for k, v in expected.items()):
        raise ValueError('固件配置不满足产品启动、ext4 更新或内存要求')
    imx(folder / 'u-boot-dtb.imx')
    return sums


def component(kind, path):
    p = Path(path)
    size = p.stat().st_size
    if not 40 <= size <= BUFFER:
        raise ValueError(f'{kind} 文件超出 16 MiB 下载缓冲区或过短')
    with p.open('rb') as stream:
        head = stream.read(40)
    if kind == 'kernel':
        if head[36:40] != struct.pack('<I', 0x016f2818):
            raise ValueError('kernel 必须为 ARM zImage')
    elif kind == 'dtb':
        if head[:4] != b'\xd0\x0d\xfe\xed' or struct.unpack_from('>I', head, 4)[0] != size:
            raise ValueError('DTB magic/长度不合法')
        command(['dtc', '-I', 'dtb', '-O', 'dts', '-o', os.devnull, p])
        compatible = command(['fdtget', '-t', 's', p, '/', 'compatible']).split()
        if '100ask,imx6ull-pro' not in compatible:
            raise ValueError('DTB 不属于当前板卡')
    return {'path': str(p.resolve()), 'bytes': size, 'sha256': sha256(p)}


def verify_sums(folder):
    folder = Path(folder)
    records = {}
    for line in (folder / 'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_./-]+)', line)
        if not match:
            raise ValueError('校验清单格式错误')
        digest, name = match.groups()
        p = PurePosixPath(name)
        if (p.is_absolute() or '..' in p.parts or str(p) != name or name == 'SHA256SUMS'
                or name in records):
            raise ValueError('校验清单路径非法或重复')
        source = folder / name
        if (any((folder / PurePosixPath(*p.parts[:n])).is_symlink() for n in range(1, len(p.parts) + 1))
                or not source.is_file() or sha256(source) != digest):
            raise ValueError(f'校验失败：{name}')
        records[name] = digest
    if not records:
        raise ValueError('校验清单为空')
    return records


def write_sums(folder):
    root = Path(folder)
    (root / 'SHA256SUMS').write_text(''.join(
        f'{sha256(p)}  {p.relative_to(root).as_posix()}\n'
        for p in sorted(root.rglob('*')) if p.is_file() and p != root / 'SHA256SUMS'))


def ext4_info(path, writable=False):
    p = Path(path)
    with p.open('rb') as stream:
        stream.seek(1024)
        sb = stream.read(1024)
    return superblock(sb, p.stat().st_size, writable)


def superblock(sb, bytes_limit, writable=False):
    if len(sb) != 1024 or struct.unpack_from('<H', sb, 56)[0] != 0xef53:
        raise ValueError('不是 ext4 文件系统')
    blocks, free = struct.unpack_from('<I', sb, 4)[0], struct.unpack_from('<I', sb, 12)[0]
    log = struct.unpack_from('<I', sb, 24)[0]
    compat, incompat, ro = struct.unpack_from('<III', sb, 92)
    if log != 2:
        raise ValueError('本产品 ext4 必须使用 4096 字节块')
    if incompat & 0x80:
        blocks += struct.unpack_from('<I', sb, 336)[0] << 32
        free += struct.unpack_from('<I', sb, 344)[0] << 32
    if blocks * BLOCK != bytes_limit or free > blocks:
        raise ValueError('文件系统与分区容量不一致')
    if writable:
        # Match the fixed revision's supported features, require a clean journal.
        if (incompat & ~0x2c2 or ro & ~0x7b or incompat & 4
                or not compat & 4 or struct.unpack_from('<H', sb, 58)[0] != 1):
            raise ValueError('kernel ext4 的特性或 journal 状态不支持 U-Boot 写入')
    return {'bytes': blocks * BLOCK, 'free_bytes': free * BLOCK,
            'compat': compat, 'incompat': incompat, 'ro_compat': ro,
            'uuid': sb[104:120].hex()}


def validate_sparse(path, scratch, expected_bytes, *, writable=False, reserve=0):
    sparse = Sparse(path)
    if sparse.blocks * BLOCK != expected_bytes:
        raise ValueError('Sparse 展开容量与目标分区不一致')
    raw = Path(scratch) / (Path(path).name + '.raw')
    sparse.extract(raw)
    info = ext4_info(raw, writable)
    count, allocated = ext4_allocated(raw)
    if not sparse.covers(allocated):
        raise ValueError('Sparse 跳过了 ext4 已分配内容或元数据')
    if info['free_bytes'] < reserve:
        raise ValueError('文件系统剩余空间低于制像预留量')
    return sparse, raw, info


def make_ext4(tree, output, sectors, label, *, new_session=True):
    bytes_limit = sectors * 512
    if bytes_limit < 32 * 1024 * 1024:
        raise ValueError('带 journal 的 ext4 至少为 32 MiB')
    with Path(output).open('xb') as stream:
        stream.truncate(bytes_limit)
    # Writable kernel inputs carry no host SELinux labels or other xattrs.
    # No metadata_csum, 64bit or directory hash trees on the writable kernel FS.
    inode_count = max(bytes_limit // 16384, sum(1 for _ in Path(tree).rglob('*')) + 16)
    command(['mkfs.ext4', '-q', '-F', '-b', str(BLOCK), '-I', '256', '-m', '0', '-N', inode_count,
             '-O', 'has_journal,extent,filetype,sparse_super,large_file,^metadata_csum,^64bit,^orphan_file,^dir_index,^flex_bg',
             '-E', 'lazy_itable_init=0,lazy_journal_init=0' + (',no_copy_xattrs' if label == 'kernel' else ''), '-L', label,
             '-d', tree, output], new_session=new_session)
    command(['e2fsck', '-fn', output], new_session=new_session)


def archive(folder, target):
    folder, target = Path(folder).resolve(), Path(target).resolve()
    if target.is_relative_to(folder):
        raise ValueError('归档输出不能位于待归档目录内部')
    verify_sums(folder)
    with tarfile.open(target, 'x:gz', format=tarfile.PAX_FORMAT) as tf:
        for p in sorted(folder.rglob('*')):
            if p.is_symlink() or not (p.is_file() or p.is_dir()):
                raise ValueError('部署归档仅允许目录和普通文件')
            info = tf.gettarinfo(str(p), arcname=p.relative_to(folder).as_posix())
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ''
            with p.open('rb') if p.is_file() else open(os.devnull, 'rb') as stream:
                tf.addfile(info, stream if info.isfile() else None)


def unpack(source, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(source) as tf:
        seen = set()
        for m in tf.getmembers():
            p = PurePosixPath(m.name)
            if (p.is_absolute() or '..' in p.parts or str(p) != m.name
                    or not (m.isfile() or m.isdir()) or m.name in seen):
                raise ValueError('部署归档含越界路径、重复成员或特殊文件')
            seen.add(m.name)
        tf.extractall(output, filter='data')
    return load_bundle(output)


def load_bundle(folder):
    folder = Path(folder)
    records = verify_sums(folder)
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()}
    if actual != set(records) | {'SHA256SUMS'} or any(p.is_symlink() for p in folder.rglob('*')):
        raise ValueError('归档含未校验的文件或符号链接')
    manifest = json_file(folder / 'manifest.json')
    if set(manifest) != {'schema', 'targets', 'firmware_target', 'files'} or manifest['schema'] != 1:
        raise ValueError('归档清单 schema 或字段错误')
    mapping = targets(manifest['targets'])
    firmware_target(manifest['firmware_target'])
    files = manifest['files']
    if set(files) != {'mbr', 'uboot', 'kernel', 'dtb', 'kernel_sparse', 'rtfs_sparse', 'boot_config'}:
        raise ValueError('归档组件不完整')
    if len(set(files.values())) != len(files) or any(name not in records for name in files.values()):
        raise ValueError('归档载荷路径冲突或缺少校验')
    paths = {k: folder / v for k, v in files.items()}
    if paths['uboot'].name != 'u-boot-dtb.imx':
        raise ValueError('固件必须消费 M1 发布目录中的构建产物')
    validate_firmware(paths['uboot'].parent)
    component('kernel', paths['kernel'])
    component('dtb', paths['dtb'])
    data = paths['mbr'].read_bytes()
    m, parts = geometry(data, mapping)
    text = paths['boot_config'].read_text()
    entry = parse_boot(text)
    if (entry['kernel'] != mapping['kernel']['path'] or entry['dtb'] != mapping['dtb']['path']
            or boot_root(entry, m['signature'], parts) != mapping['rtfs']['partition']):
        raise ValueError('归档启动描述与组件目标不一致')
    images = {}
    with tempfile.TemporaryDirectory(prefix='uuf-check-') as temp:
        for name in ('kernel', 'rtfs'):
            part = parts[mapping[name]['partition']]
            sp, raw, info = validate_sparse(paths[name + '_sparse'], temp, part['sectors'] * 512,
                                           writable=name == 'kernel')
            images[name] = {'sparse': sp.summary(), 'fs': info}
            if name == 'kernel':
                for kind, path in (('kernel', mapping['kernel']['path']), ('dtb', mapping['dtb']['path']),
                                   ('boot_config', '/extlinux/extlinux.conf')):
                    out = Path(temp) / (kind + '.extracted')
                    command(['debugfs', '-R', f'dump {path} {out}', raw])
                    if not out.is_file() or sha256(out) != sha256(paths[kind]):
                        raise ValueError(f'kernel 分区内 {kind} 与归档原始组件不一致')
    return {'folder': folder, 'manifest': manifest, 'paths': paths, 'mbr': data,
            'parts': parts, 'images': images, 'sums': records}


def pack(request):
    """Both ext4 filesystems are new, even when only one partition changed."""
    from .rootfs import tree_catalog
    output = Path(request['output']).resolve()
    source = Path(request['rootfs']).resolve()
    mapping = targets(request['targets'])
    data = Path(request['mbr']).read_bytes()
    _, parts = geometry(data, mapping)
    fw = firmware_target(request.get('firmware_target') or ROOT / 'firmware/target.json')
    validate_firmware(request['firmware'])
    component('kernel', request['kernel'])
    component('dtb', request['dtb'])
    text = boot_text(json_file(request['boot']), mapping, data)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(request['firmware'], output / 'firmware')
    for name, arg in (('kernel.bin', 'kernel'), ('board.dtb', 'dtb')):
        src = Path(request[arg])
        original = sha256(src)
        shutil.copyfile(src, output / name)
        if sha256(output / name) != original:
            raise ValueError('打包期间组件输入变化')
    (output / 'mbr.bin').write_bytes(data)
    (output / 'extlinux.conf').write_text(text)
    with tempfile.TemporaryDirectory(prefix='prepare-', dir=output) as temp:
        work = Path(temp)
        tree = work / 'kernel-tree'
        tree.mkdir()
        for kind, src in (('kernel', output / 'kernel.bin'), ('dtb', output / 'board.dtb'),
                          ('config', output / 'extlinux.conf')):
            path = '/extlinux/extlinux.conf' if kind == 'config' else mapping[kind]['path']
            dest = tree / path.lstrip('/')
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            dest.chmod(0o644)
        make_ext4(tree, work / 'kernel.ext4', parts[mapping['kernel']['partition']]['sectors'], 'kernel')
        owner_script = work / 'ownership.txt'
        owner_script.write_text(''.join(f'set_inode_field {p} {k} 0\n'
                                       for p in ['/'] + ['/' + p.relative_to(tree).as_posix() for p in tree.rglob('*')]
                                       for k in ('uid', 'gid')))
        command(['debugfs', '-w', '-f', owner_script, work / 'kernel.ext4'])
        worker = {'source': str(source), 'tree': str(work / 'root-tree'), 'image': str(work / 'rtfs.ext4'),
                  'sectors': parts[mapping['rtfs']['partition']]['sectors'],
                  'kernel_partition': mapping['kernel']['partition'],
                  'linux_boot_device': request.get('linux_boot_device')}
        if source.is_dir():
            catalog = work / 'rootfs-catalog.json'
            catalog.write_text(json.dumps(tree_catalog(source)))
            worker['catalog'] = str(catalog)
        description = work / 'rootfs-worker.json'
        description.write_text(json.dumps(worker))
        import sys
        command(['fakeroot', '--', sys.executable, ROOT / 'uuf', '_rootfs', '--request', description], timeout=300)
        for name in ('kernel', 'rtfs'):
            raw = work / (name + '.ext4')
            info = ext4_info(raw, name == 'kernel')
            reserve = request[name + '_reserve']
            if type(reserve) is not int or reserve < 0 or info['free_bytes'] < reserve:
                raise ValueError(f'{name} 制像预留量不足')
            blocks, allocated = ext4_allocated(raw)
            encode_sparse(raw, output / (name + '.sparse'), blocks, allocated)
    manifest = {'schema': 1, 'targets': mapping, 'firmware_target': fw,
                'files': {'mbr': 'mbr.bin', 'uboot': 'firmware/u-boot-dtb.imx',
                          'kernel': 'kernel.bin', 'dtb': 'board.dtb', 'kernel_sparse': 'kernel.sparse',
                          'rtfs_sparse': 'rtfs.sparse', 'boot_config': 'extlinux.conf'}}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    write_sums(output)
    checked = load_bundle(output)
    if request.get('archive'):
        archive(output, request['archive'])
    return {'bundle': str(output), 'archive': request.get('archive'),
            'images': checked['images'], 'manifest': manifest}
