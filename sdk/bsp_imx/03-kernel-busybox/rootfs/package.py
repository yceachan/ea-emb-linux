#!/usr/bin/env python3
"""Assemble the eMMC rootfs tree and archive without root."""
import argparse
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

BSP = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def entries(tree):
    return sorted(tree.rglob('*'), key=lambda p: (len(p.relative_to(tree).parts), str(p)))


def copy_overlay(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)


def write_tar(tree, output):
    with output.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
            for path in entries(tree):
                info = archive.gettarinfo(str(path), arcname=path.relative_to(tree).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = 0
                if info.isfile():
                    with path.open('rb') as data:
                        archive.addfile(info, data)
                else:
                    archive.addfile(info)


def check_applets(tree, links):
    available = {Path(line).name for line in links.read_text().splitlines()}
    required = {'init', 'sh', 'mount', 'umount', 'mountpoint', 'hostname', 'stty', 'ls',
                'cat', 'cp', 'mv', 'rm', 'mkdir', 'ln', 'chmod', 'find', 'grep', 'sed',
                'awk', 'test', 'printf', 'sleep', 'uname', 'dmesg', 'ps', 'free', 'df',
                'du', 'hexdump', 'dd', 'sync', 'sha256sum', 'tar', 'gunzip', 'stat',
                'readlink', 'id', 'kill', 'reboot', 'poweroff'}
    missing = required - available
    if missing:
        raise ValueError(f'构建缺少 applet：{sorted(missing)}')
    for line in links.read_text().splitlines():
        link = tree / line.lstrip('/')
        if not link.is_symlink():
            raise ValueError(f'安装缺少 applet 链接：{line}')


def assemble(work, kernel, output):
    os.umask(0o022)
    out = work / 'out'
    subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=out, check=True)
    if (out / 'source-revision').read_text().strip() != (BSP / 'rootfs/base-revision').read_text().strip():
        raise ValueError('BusyBox 构建版本与当前 rootfs 输入不符')
    expected = {line for line in (BSP / 'rootfs/board.config').read_text().splitlines()
                if line.startswith('CONFIG_')}
    if not expected <= set((out / '.config').read_text().splitlines()):
        raise ValueError('已有 BusyBox 配置不满足当前 rootfs 输入')
    subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=kernel, check=True)
    if digest(work / 'install/bin/busybox') != digest(out / 'busybox'):
        raise ValueError('安装树 BusyBox 与校验通过的产物不一致')
    output.mkdir()
    target = output / 'rootfs'
    shutil.copytree(work / 'install', target, symlinks=True)
    check_applets(target, out / 'busybox.links')
    copy_overlay(BSP / 'rootfs/overlay', target)
    for name in ['dev', 'proc', 'sys', 'run', 'tmp', 'root', 'mnt']:
        (target / name).mkdir(exist_ok=True)
    (target / 'tmp').chmod(0o1777)
    (target / 'etc/mtab').symlink_to('/proc/mounts')
    shutil.copyfile(kernel / 'arch/arm/boot/zImage', target / 'boot/zImage')
    shutil.copyfile(kernel / 'arch/arm/boot/dts/nxp/imx/imx6ull-100ask-pro.dtb',
                    target / 'boot/imx6ull-100ask-pro.dtb')
    (target / 'etc/build-info').write_text(
        f"kernel={ (kernel / 'source-revision').read_text().strip() }\n"
        f"busybox={ (out / 'source-revision').read_text().strip() }\n")
    (target / 'boot/SHA256SUMS').write_text(''.join(
        f'{digest(target / "boot" / name)}  {name}\n'
        for name in ['zImage', 'imx6ull-100ask-pro.dtb', 'extlinux/extlinux.conf']))
    write_tar(target, output / 'rootfs.tar.gz')

    for name in ['zImage', 'imx6ull-100ask-pro.dtb']:
        shutil.copyfile(target / 'boot' / name, output / name)
    (output / 'SHA256SUMS').write_text(''.join(
        f'{digest(output / name)}  {name}\n'
        for name in ['zImage', 'imx6ull-100ask-pro.dtb', 'rootfs.tar.gz']))
    (output / 'package-info.txt').write_text(
        f'BusyBox source: {out}\nKernel output: {kernel}\n')
    print(f'打包完成：{output}；rootfs.tar.gz 包含 kernel、DTB 与 BusyBox。')



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('busybox_work', type=Path)
    parser.add_argument('kernel_out', type=Path)
    parser.add_argument('new_output', type=Path)
    args = parser.parse_args()
    assemble(args.busybox_work.resolve(), args.kernel_out.resolve(), args.new_output.resolve())
