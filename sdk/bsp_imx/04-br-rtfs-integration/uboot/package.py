#!/usr/bin/env python3
"""Assemble a download package; runs only host image tools, never UUU/USB."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import firmware
from images import (BLOCK, BOOTCONF, DTB, command, encode_sparse, ext4_allocated,
                    layout, preflight_images, sha256, validate_files, verify_sums, write_sums)

BSP = Path(__file__).resolve().parent
BUILD = BSP.parent / "build/uboot"


def package(args):
    config = layout(BSP / "layout.json")
    p1, p2 = config["p1"], config["p2"]
    fw = args.firmware.resolve()
    verify_sums(fw, {"u-boot-dtb.imx", ".config", "source-revision", "bsp-inputs.sha256", "image-info.txt"})
    if (fw / "bsp-inputs.sha256").read_text() != firmware.inputs(BSP):
        raise ValueError("固件构建快照不是当前 04 输入")
    rootfs = args.rootfs.resolve()
    blocks, allocated = ext4_allocated(rootfs)
    if blocks * BLOCK != p2["sectors"] * 512:
        raise ValueError(f"rootfs 容量必须等于 p2：{p2['sectors'] * 512} 字节")
    out = args.output.resolve()
    if any(c.isspace() for c in str(out)):
        raise ValueError("下载包路径不能包含空白（UUU 文件参数约束）")
    out.mkdir(parents=True, exist_ok=False)
    for source, dest in ((fw / "u-boot-dtb.imx", "loader.imx"),
                         (fw / "u-boot-dtb.imx", "product.imx"),
                         (fw / ".config", "uboot.config"),
                         (fw / "bsp-inputs.sha256", "uboot-inputs.sha256"),
                         (fw / "source-revision", "source-revision"),
                         (fw / "image-info.txt", "image-info.txt"),
                         (args.kernel, "zImage"), (args.dtb, DTB), (BSP / "layout.json", "layout.json")):
        shutil.copyfile(source, out / dest)
    (out / "extlinux.conf").write_text(BOOTCONF)
    identity = {"policy": 1, "revision": (out / "source-revision").read_text().strip(),
                "inputs_sha256": sha256(out / "uboot-inputs.sha256"),
                "config_sha256": sha256(out / "uboot.config"),
                "image_sha256": sha256(out / "loader.imx")}
    (out / "firmware.json").write_text(json.dumps(identity, indent=2) + "\n")
    firmware.validate(out, BSP)
    validate_files(out)
    assemble_images(out, rootfs, config, blocks, allocated, BUILD)
    write_sums(out)
    print(f"下载包已生成并通过文件系统/块映射预检：{out}")
    print("尚未访问板卡；下一步 flash.py all --package ... --dry-run")


def assemble_images(out, rootfs, config, blocks, allocated, build):
    """Create/validate actual images independently of firmware binding."""
    p1, p2 = config["p1"], config["p2"]
    build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-", dir=build) as temporary:
        work = Path(temporary)
        staging, empty, tmp = work / "input", work / "root", work / "tmp"
        staging.mkdir()
        empty.mkdir()
        (staging / "extlinux").mkdir()
        for name in ("zImage", DTB):
            shutil.copyfile(out / name, staging / name)
        shutil.copyfile(out / "extlinux.conf", staging / "extlinux/extlinux.conf")
        (staging / "rootfs.ext4").symlink_to(rootfs)
        cfg = f'''image boot.fat {{
  vfat {{
    files = {{ "zImage", "{DTB}", "extlinux" }}
    label = "IMXBOOT"
    extraargs = "-F 32"
  }}
  size = {p1["sectors"] * 512}
}}
image system.raw.img {{
  hdimage {{ partition-table-type = "mbr" }}
  partition boot {{
    partition-type = 0x0c
    bootable = true
    image = "boot.fat"
    offset = {p1["start"] * 512}
    size = {p1["sectors"] * 512}
  }}
  partition rootfs {{
    partition-type = 0x83
    image = "rootfs.ext4"
    offset = {p2["start"] * 512}
    size = {p2["sectors"] * 512}
  }}
}}
'''
        (out / "genimage.cfg").write_text(cfg)
        command(["genimage", "--config", out / "genimage.cfg", "--rootpath", empty,
                 "--inputpath", staging, "--outputpath", out, "--tmppath", tmp], timeout=600)
        end = (p2["start"] + p2["sectors"]) // 8
        shift = p2["start"] // 8
        # Store the entire MBR block and FAT, only skip bitmap-proven ext4 free
        # blocks and inter-partition gaps. Host file holes are not trusted.
        ranges = [(0, 1), (p1["start"] // 8, (p1["start"] + p1["sectors"]) // 8)]
        ranges += [(a + shift, b + shift) for a, b in allocated]
        encode_sparse(out / "system.raw.img", out / "system.sparse.img", end, ranges)
        encode_sparse(rootfs, out / "rootfs.sparse.img", blocks, allocated)
        check = work / "check"
        check.mkdir()
        system, root = preflight_images(out, check, config)
        (out / "image-map.json").write_text(json.dumps(
            {"system": system.summary(), "rootfs": root.summary()}, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description="04 整盘/组件下载包制作（仅主机操作）")
    parser.add_argument("--firmware", type=Path, default=BUILD / "firmware/out")
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--rootfs", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=BUILD / "download")
    package(parser.parse_args())


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
