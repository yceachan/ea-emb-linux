#!/usr/bin/env python3
"""Adapt the pinned, closed 03 BusyBox archive into 04 U-Boot validation images.
Host files only: never builds SDK components, executes target ELF, or runs UUU.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
UBOOT = HERE.parent
BUILD = UBOOT.parent / "build/uboot"
sys.path.insert(0, str(UBOOT / "tools"))
from images import BOOTCONF, DTB, command, ext4_allocated, layout, sha256, verify_sums, write_sums

BASE_REQUIRED = {"zImage", DTB, "rootfs.tar.gz"}


def baseline(source):
    record = json.loads((HERE / "baseline.json").read_text())
    sums = verify_sums(source, BASE_REQUIRED)
    if {name: sums[name] for name in BASE_REQUIRED} != record["files"]:
        raise ValueError("输入不是已锁定的 03 BusyBox r2 归档，不接受自重算清单代替基线")
    with tarfile.open(source / "rootfs.tar.gz") as archive:
        for name in ("bin/busybox", "etc/build-info", "etc/init.d/rcS", "etc/inittab",
                     "boot/zImage", "boot/" + DTB):
            if not archive.getmember(name).isfile():
                raise ValueError(f"基线关键文件不是普通文件：{name}")
        info = dict(line.split("=", 1) for line in archive.extractfile("etc/build-info").read().decode().splitlines())
        if info != {"kernel": record["kernel_revision"], "busybox": record["busybox_revision"]}:
            raise ValueError("归档源码身份与关闭的 03 基线不符")
        import hashlib
        for name in ("zImage", DTB):
            digest = hashlib.file_digest(archive.extractfile("boot/" + name), "sha256").hexdigest()
            if digest != sums[name]:
                raise ValueError(f"归档中的 {name} 与独立组件不一致")
    return record


def extract_tree(archive_path, tree):
    """Preserve target links without ever writing through a host symlink.
    All target symlinks (including /proc/mounts) are created last. Only root-owned
    directories, regular files and symlinks are allowed; no device nodes/links.
    """
    with tarfile.open(archive_path) as archive:
        items = archive.getmembers()
        seen, expanded = set(), 0
        for member in items:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.as_posix() in seen:
                raise ValueError(f"非法或重复的归档路径：{member.name}")
            seen.add(path.as_posix())
            if not (member.isdir() or member.isfile() or member.issym()) or member.uid or member.gid:
                raise ValueError(f"归档不符合 root 文件树约束：{member.name}")
            expanded += member.size
        if len(items) > 10000 or expanded > 128 * 1024 * 1024:
            raise ValueError("归档超过已知 BusyBox 文件树限额")
        links = {PurePosixPath(m.name).as_posix() for m in items if m.issym()}
        for member in items:
            path = PurePosixPath(member.name)
            if any(parent.as_posix() in links for parent in path.parents):
                raise ValueError(f"归档试图穿过符号链接目录：{member.name}")
        tree.mkdir()
        for member in sorted(items, key=lambda m: (m.issym(), len(PurePosixPath(m.name).parts), m.name)):
            dest = tree / member.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                dest.mkdir(exist_ok=True)
            elif member.isfile():
                with archive.extractfile(member) as src, dest.open("xb") as dst:
                    shutil.copyfileobj(src, dst)
            else:
                dest.symlink_to(member.linkname)
            if not member.issym():
                dest.chmod(member.mode & 0o1777)
                os.utime(dest, (member.mtime, member.mtime))
            os.chown(dest, 0, 0, follow_symlinks=False)
        os.chown(tree, 0, 0)


def adapt_tree(tree, record, config):
    elf = command(["readelf", "-h", tree / "bin/busybox"])
    program = command(["readelf", "-l", tree / "bin/busybox"])
    if "Machine:" not in elf or "ARM" not in elf or "hard-float ABI" not in elf or "INTERP" in program:
        raise ValueError("BusyBox 不是所需的 ARM hard-float 静态 ELF")
    binary_hash = sha256(tree / "bin/busybox")
    # Boot files now belong to p1. Keeping old p2 /boot copies would let a shell
    # checksum falsely validate files that U-Boot did not actually load.
    shutil.rmtree(tree / "boot")
    (tree / "boot").mkdir()
    metadata = tree / "etc/uboot-validation"
    metadata.mkdir()
    identity = dict(record, busybox_binary_sha256=binary_hash,
                    adaptation=["boot files moved from p2 /boot into p1 FAT root",
                                "p2 rebuilt at 2 GiB; init/BusyBox/kernel/DTB unchanged",
                                "read-only runtime verifier added; no dependency on Linux VFAT"],
                    board_acceptance="pending")
    (metadata / "baseline.json").write_text(json.dumps(identity, indent=2) + "\n")
    values = {"KERNEL_RELEASE": record["kernel_release"], "BUSYBOX_SHA256": binary_hash,
              "KERNEL_REVISION": record["kernel_revision"], "BUSYBOX_REVISION": record["busybox_revision"],
              "P1_START": str(config["p1"]["start"]), "P1_SECTORS": str(config["p1"]["sectors"]),
              "P2_START": str(config["p2"]["start"]), "P2_SECTORS": str(config["p2"]["sectors"])}
    (metadata / "expected.env").write_text("".join(f"{key}='{value}'\n" for key, value in values.items()))
    shutil.copyfile(HERE / "verify-board.sh", tree / "sbin/verify-uboot-busybox")
    (tree / "sbin/verify-uboot-busybox").chmod(0o755)
    for file in (metadata, metadata / "baseline.json", metadata / "expected.env",
                 tree / "boot", tree / "sbin/verify-uboot-busybox"):
        os.chown(file, 0, 0)
    return identity


def prepare(args, record, config):
    source, out = args.baseline.resolve(), args.output.resolve()
    if out.is_relative_to(source):
        raise ValueError("输出不能位于 03 基线输入目录中")
    out.mkdir(parents=True, exist_ok=False)
    tree = out / "rootfs"
    extract_tree(source / "rootfs.tar.gz", tree)
    identity = adapt_tree(tree, record, config)
    for name in ("zImage", DTB):
        shutil.copyfile(source / name, out / name)
    shutil.copyfile(UBOOT / "layout.json", out / "layout.json")
    (out / "extlinux.conf").write_text(BOOTCONF)
    rootfs = out / "rootfs.ext4"
    with rootfs.open("xb") as stream:
        stream.truncate(config["p2"]["sectors"] * 512)
    command(["mkfs.ext4", "-F", "-b", "4096", "-m", "0", "-L", "uboot-busybox",
             "-U", "f7d424ef-bd56-4b52-8822-f5ec8e15c304", "-O",
             "none,has_journal,ext_attr,resize_inode,dir_index,filetype,extent,sparse_super,large_file",
             "-E", "lazy_itable_init=0,lazy_journal_init=0", "-d", tree, rootfs])
    blocks, allocated = ext4_allocated(rootfs)
    for name in ("/bin/busybox", "/etc/uboot-validation/baseline.json", "/sbin/verify-uboot-busybox"):
        status = command(["debugfs", "-R", f"stat {name}", rootfs])
        if "User:     0" not in status or "Group:     0" not in status:
            raise ValueError(f"ext4 文件元数据不是 root：{name}\n{status}")
    spec = importlib.util.spec_from_file_location("uboot_package", UBOOT / "package.py")
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    package.assemble_images(out, rootfs, config, blocks, allocated, BUILD)
    identity.update({"source_directory": str(source), "layout": config,
                     "host_images": "passed", "deployment_package": "pending current firmware binding",
                     "boot_partition_sha256": sha256(out / "boot.fat")})
    (out / "validation.json").write_text(json.dumps(identity, indent=2) + "\n")
    write_sums(out)
    print(f"真实 03 BusyBox 验收镜像已生成：{out}")
    print("没有执行 SDK 构建、UUU、串口操作或硬件写入；板级验收状态为 pending。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=UBOOT.parent.parent /
                        "03-kernel-busybox/artifacts/2026-10-07-busybox-r2")
    parser.add_argument("--output", type=Path, default=BUILD / "busybox-validation/payload")
    parser.add_argument("--dry-run", action="store_true", help="只读检查归档身份及输入，不生成镜像")
    parser.add_argument("--_fakeroot-worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    record = baseline(args.baseline.resolve())
    config = layout(UBOOT / "layout.json")
    if args.dry_run:
        print(json.dumps({"baseline": record, "layout": config, "output": str(args.output.resolve()),
                          "writes": "host output only; no SDK build/UUU/target operation"}, ensure_ascii=False, indent=2))
        return
    if not args._fakeroot_worker:
        command(["fakeroot", sys.executable, __file__, "--_fakeroot-worker", "--baseline", args.baseline.resolve(),
                 "--output", args.output.resolve()], timeout=600)
        print(f"BusyBox 验收镜像通过主机检查：{args.output.resolve()}；实板验收仍待完成。")
        return
    if not os.environ.get("FAKEROOTKEY"):
        raise ValueError("worker 必须由 fakeroot 启动，不能以 host UID 打包 target rootfs")
    prepare(args, record, config)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
