"""Rebuild rootfs from a tree or tar while fakeroot retains inode ownership."""
import base64
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tarfile

from .package import make_ext4, ext4_info


def member_path(name):
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts:
        raise ValueError('rootfs 归档路径越界')
    return p.as_posix()


def tar_members(source):
    with tarfile.open(source) as tf:
        members = tf.getmembers()
    seen, links = set(), set()
    for m in members:
        name = member_path(m.name)
        if name in seen or name == '.' and not m.isdir():
            raise ValueError('rootfs 归档路径重复或根条目非法')
        seen.add(name)
        if not 0 <= m.uid < 0xffffffff or not 0 <= m.gid < 0xffffffff:
            raise ValueError('rootfs UID／GID 无法由目标文件系统表示')
        if not (m.isfile() or m.isdir() or m.issym() or m.islnk() or m.ischr() or m.isblk() or m.isfifo()):
            raise ValueError('rootfs 归档包含不支持的条目')
        if any('xattr' in k or 'acl' in k.lower() for k in m.pax_headers):
            raise ValueError('含扩展属性／ACL 的 tar 暂不支持；提供保留属性的目录树')
        if m.issym() or m.islnk():
            links.add(name)
    for name in seen:
        if any(PurePosixPath(*PurePosixPath(name).parts[:n]).as_posix() in links
               for n in range(1, len(PurePosixPath(name).parts))):
            raise ValueError('rootfs 归档不能通过链接父目录写入')
    regular = {member_path(m.name) for m in members if m.isfile()}
    if any(m.islnk() and member_path(m.linkname) not in regular for m in members):
        raise ValueError('rootfs hardlink 必须指向归档内普通文件')
    return members


def tree_catalog(source):
    source = Path(source)
    records, inodes = [], {}
    for path in [source, *sorted(source.rglob('*'))]:
        s = path.lstat()
        name = path.relative_to(source).as_posix()
        entry = {'name': name, 'uid': s.st_uid, 'gid': s.st_gid,
                 'mode': stat.S_IMODE(s.st_mode), 'mtime': s.st_mtime,
                 'xattrs': {k: base64.b64encode(os.getxattr(path, k, follow_symlinks=False)).decode()
                           for k in os.listxattr(path, follow_symlinks=False)}}
        if not stat.S_ISREG(s.st_mode) and not stat.S_ISDIR(s.st_mode) and s.st_nlink > 1:
            raise ValueError('目录树中的特殊文件 hardlink 暂不支持')
        if stat.S_ISDIR(s.st_mode):
            entry['kind'] = 'dir'
        elif stat.S_ISLNK(s.st_mode):
            entry.update(kind='symlink', link=os.readlink(path))
        elif stat.S_ISREG(s.st_mode):
            key = (s.st_dev, s.st_ino)
            if key in inodes:
                entry.update(kind='hardlink', link=inodes[key], size=0)
            else:
                inodes[key] = name
                entry.update(kind='file', size=s.st_size)
        elif stat.S_ISCHR(s.st_mode) or stat.S_ISBLK(s.st_mode):
            entry.update(kind='char' if stat.S_ISCHR(s.st_mode) else 'block',
                         major=os.major(s.st_rdev), minor=os.minor(s.st_rdev))
        elif stat.S_ISFIFO(s.st_mode):
            entry['kind'] = 'fifo'
        else:
            raise ValueError(f'rootfs 目录含不支持的类型：{path}')
        records.append(entry)
    return records


def payload_size(source):
    source = Path(source)
    if source.is_dir():
        records = tree_catalog(source)
        sizes = [r.get('size', 0) for r in records]
    else:
        records = tar_members(source)
        sizes = [m.size for m in records if m.isfile()]
    return sum((n + 4095) // 4096 * 4096 for n in sizes) + len(records) * 4096


def prepare(request):
    """Internal worker; called inside fakeroot by the public pack operation."""
    source, tree, image = map(Path, (request['source'], request['tree'], request['image']))
    tree.mkdir()
    attrs, links = [], []
    if source.is_dir():
        records = json.loads(Path(request['catalog']).read_text())
        for entry in records:
            name, kind = entry['name'], entry['kind']
            dest = tree / name
            if kind == 'dir':
                dest.mkdir(parents=True, exist_ok=True)
            elif kind in ('symlink', 'hardlink'):
                links.append(entry)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if kind == 'file':
                    shutil.copyfile(source / name, dest)
                elif kind == 'fifo':
                    os.mkfifo(dest)
                else:
                    os.mknod(dest, (stat.S_IFCHR if kind == 'char' else stat.S_IFBLK) | entry['mode'],
                             os.makedev(entry['major'], entry['minor']))
            attrs.append(entry)
    else:
        members = tar_members(source)
        with tarfile.open(source) as tf:
            for m in members:
                name = member_path(m.name)
                dest = tree / name
                kind = ('dir' if m.isdir() else 'file' if m.isfile() else 'symlink' if m.issym()
                        else 'hardlink' if m.islnk() else 'char' if m.ischr() else 'block' if m.isblk() else 'fifo')
                entry = {'name': name, 'kind': kind, 'uid': m.uid, 'gid': m.gid,
                         'mode': m.mode, 'mtime': m.mtime, 'xattrs': {}}
                if kind == 'dir':
                    dest.mkdir(parents=True, exist_ok=True)
                elif kind in ('symlink', 'hardlink'):
                    entry['link'] = m.linkname if kind == 'symlink' else member_path(m.linkname)
                    links.append(entry)
                else:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if kind == 'file':
                        with tf.extractfile(m) as src, dest.open('xb') as out:
                            shutil.copyfileobj(src, out)
                        if dest.stat().st_size != m.size:
                            raise ValueError('rootfs tar 载荷截断')
                    elif kind == 'fifo':
                        os.mkfifo(dest)
                    else:
                        os.mknod(dest, (stat.S_IFCHR if kind == 'char' else stat.S_IFBLK) | m.mode,
                                 os.makedev(m.devmajor, m.devminor))
                attrs.append(entry)
    for entry in sorted(links, key=lambda e: e['kind'] == 'symlink'):
        dest = tree / entry['name']
        dest.parent.mkdir(parents=True, exist_ok=True)
        if entry['kind'] == 'hardlink':
            os.link(tree / entry['link'], dest)
        else:
            os.symlink(entry['link'], dest)
    device = request.get('linux_boot_device')
    if device:
        if not re.fullmatch(r'/dev/mmcblk[0-9]+p[1-4]', device) or int(device[-1]) != request['kernel_partition']:
            raise ValueError('需要实测的 Linux kernel 分区设备；分区号须与 MBR 对应')
        for name in ('etc', 'etc/init.d', 'etc/init.d/rcS', 'etc/fstab', 'boot'):
            if (tree / name).is_symlink():
                raise ValueError('03 BusyBox 挂载准备不能经过符号链接')
        init = tree / 'etc/init.d/rcS'
        text = init.read_text()
        marker = 'echo "[BOOT READY]'
        if marker not in text:
            raise ValueError('挂载准备只适用于 03 BusyBox rcS 基线')
        (tree / 'boot').mkdir(exist_ok=True)
        init.write_text(text.replace(marker, f"mount -t ext4 -o rw {device} /boot || failed '挂载 kernel 分区 /boot'\n" + marker, 1))
        fstab = tree / 'etc/fstab'
        previous = fstab.read_text() if fstab.exists() else ''
        retained = []
        for line in previous.splitlines(keepends=True):
            fields = line.split('#', 1)[0].split()
            if len(fields) < 2 or fields[1] != '/boot':
                retained.append(line)
        text = ''.join(retained)
        fstab.write_text(text + ('\n' if text and not text.endswith('\n') else '')
                         + f'{device} /boot ext4 defaults 0 2\n')
    for entry in sorted(attrs, key=lambda e: len(PurePosixPath(e['name']).parts), reverse=True):
        dest = tree / entry['name']
        os.chown(dest, entry['uid'], entry['gid'], follow_symlinks=False)
        if entry['kind'] != 'symlink':
            os.chmod(dest, entry['mode'])
        os.utime(dest, (entry['mtime'], entry['mtime']), follow_symlinks=False)
        for key, value in entry['xattrs'].items():
            os.setxattr(dest, key, base64.b64decode(value), follow_symlinks=False)
    # mkfs/e2fsck stay in the outer fakeroot job group so cancellation owns
    # every nested writer even if the worker itself is terminated.
    make_ext4(tree, image, request['sectors'], 'rtfs', new_session=False)
    return ext4_info(image)
