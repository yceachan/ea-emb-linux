#!/usr/bin/env python3
"""Guarded firmware/system updates. No bypass-confirm switch."""
import argparse
from datetime import datetime
import errno
import json
import os
from pathlib import Path
import pty
import re
import selectors
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import firmware
from images import (DTB, REQUIRED, WINDOW, layout, preflight_images, sha256,
                    validate_files, verify_sums, write_sums)

BSP = Path(__file__).resolve().parent
BUILD = BSP.parent / "build/uboot"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def plain(data):
    return ANSI.sub("", data.decode("utf-8", errors="replace"))


def failed(text):
    # Installed Snap can return zero when libuuu has reported an error.
    return re.search(r"\b(?:Error|Fail|Failed)\b", text, re.I) is not None


def complete(text, script, dry=False):
    expected = [x.strip() for x in script.read_text().splitlines() if x.startswith(("SDP:", "FB:"))]
    if dry:
        actual = [x.strip() for x in text.splitlines() if x.startswith(("SDP:", "FB:"))]
        # libuuu 1.5.21 prints parsed groups in protocol-map order (FB then
        # SDP), not execution order. Compare the exact sequence within each
        # protocol, including count; do not accept substring-only success.
        return all([x for x in actual if x.startswith(prefix)] ==
                   [x for x in expected if x.startswith(prefix)]
                   for prefix in ("SDP:", "FB:"))
    steps = re.findall(r"Start Cmd:([^\r\n]+)(.*?)(?=Start Cmd:|\Z)", text, re.S)
    return ([cmd.strip() for cmd, _ in steps] == expected
            and all(re.search(r"\bOkay\b", body) for _, body in steps))


def stop(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        except ProcessLookupError:
            pass


def run_uuu(uuu, options, work, logfile, timeout, *, script=None, dry=False, check_errors=True):
    """PTY provides real-time Snap/UUU output; own deadline covers the whole task."""
    master, slave = pty.openpty()
    process = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen([uuu, *options], cwd=work, stdin=subprocess.DEVNULL,
                                   stdout=slave, stderr=slave, start_new_session=True)
        os.close(slave)
        slave = None
        with logfile.open("wb") as log, selectors.DefaultSelector() as poller:
            poller.register(master, selectors.EVENT_READ)
            eof = False
            while not eof:
                if time.monotonic() > deadline:
                    raise RuntimeError(f"UUU 超过总时限 {timeout:g} 秒；写入可能未完成，查看 {logfile}")
                for _, _ in poller.select(timeout=0.1):
                    try:
                        data = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        data = b""
                    if not data:
                        eof = True
                        break
                    log.write(data)
                    log.flush()
                    sys.stdout.buffer.write(data)
                    sys.stdout.buffer.flush()
            status = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        text = plain(logfile.read_bytes())
        if status or (check_errors and failed(text)):
            raise RuntimeError(f"UUU 报告失败（退出码 {status}），查看 {logfile}")
        if script is not None and not complete(text, script, dry):
            raise RuntimeError(f"UUU 命令/成功记录不完整，查看 {logfile}")
        return text
    finally:
        if process is not None:
            stop(process)
        if slave is not None:
            os.close(slave)
        os.close(master)


def rom_devices(text):
    paths = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[1:3] == ["MX6ULL", "SDP:"]:
            if [x.lower() for x in fields[3:5]] == ["0x15a2", "0x0080"]:
                if not re.fullmatch(r"[0-9]+:[0-9]+(?:\.[0-9]+)*", fields[0]):
                    raise ValueError("UUU 返回非法 USB 路径")
                paths.append(fields[0])
    return paths


def select_rom(text, requested):
    paths = rom_devices(text)
    if requested:
        if paths.count(requested) != 1:
            raise ValueError(f"没有找到指定 ROM USB 设备：{requested}")
        return requested
    if len(paths) != 1:
        raise ValueError(f"发现 {len(paths)} 块 i.MX6ULL ROM 设备；需恰好一块，或显式指定 --usb-path")
    return paths[0]


def script_for(mode, work, config, system, rootfs):
    p1, p2 = config["p1"], config["p2"]
    commands = ["uuu_version 1.2.39", "SDP: dcd -f loader.imx",
                "SDP: write -f loader.imx -ivt 0", "SDP: jump -f loader.imx -ivt 0"]
    def ucmd(text):
        commands.append("FB: ucmd " + text)
    values = " ".join(f'{p[k]:x}' for p in (p1, p2) for k in ("start", "sectors"))
    ucmd(f"imx04 guard {mode} {values}")
    slots = 0
    def save(hw, start, count):
        nonlocal slots
        if slots >= 1024:
            raise ValueError("保护区域超出板端快照槽位")
        ucmd(f"imx04 save {slots:x} {hw:x} {start:x} {count:x}")
        slots += 1
    if mode != "all":
        save(1, 0, 0)  # entire physical boot0, not just the bootloader file
        # MBR and leading gap; p1 for rootfs, p2 for kernel/DTB.
        regions = [(0, p2["start"])] if mode == "rootfs" else [
            (0, p1["start"]), (p1["start"] + p1["sectors"], p2["start"] - p1["start"] - p1["sectors"]),
            (p2["start"], p2["sectors"])]
        for start, count in regions:
            for offset in range(0, count, WINDOW // 512):
                save(0, start + offset, min(count - offset, WINDOW // 512))
        if mode in ("kernel", "dtb"):
            filename = "zImage" if mode == "kernel" else DTB
            ucmd(f"imx04 space {filename} {(work / filename).stat().st_size:x}")
            for name in ("zImage", DTB, "extlinux/extlinux.conf"):
                if name != filename:
                    ucmd(f"imx04 filesave {slots:x} {name}")
                    slots += 1
    if mode == "all":
        commands.append("FB: flash all system.sparse.img")
        # Refresh partition parser and check the actual new MBR before boot0.
        ucmd(f"imx04 guard rootfs {values}")
        for lba, sectors, digest in system.checks():
            ucmd(f"imx04 verify 0 {lba:x} {sectors:x} {digest}")
        commands.append("FB: flash bootloader product.imx")
        ucmd(f"imx04 verify 1 2 {(work / 'product.imx').stat().st_size // 512:x} {sha256(work / 'product.imx')}")
        ucmd("mmc partconf 1 1 1 0")
        ucmd("imx04 bootconf 48")
    elif mode == "rootfs":
        commands.append("FB: flash rootfs rootfs.sparse.img")
        for lba, sectors, digest in rootfs.checks(p2["start"]):
            ucmd(f"imx04 verify 0 {lba:x} {sectors:x} {digest}")
    else:
        filename = "zImage" if mode == "kernel" else DTB
        size = (work / filename).stat().st_size
        commands.append(f"FB: download -f {filename}")
        # Assert filesize as well as content after reading the FAT file back.
        ucmd(f"fatwrite mmc 1:1 0x82000000 {filename} ${{filesize}}")
        ucmd(f"imx04 file {filename} {size:x} {sha256(work / filename)}")
    for slot in range(slots):
        ucmd(f"imx04 keep {slot:x}")
    if mode != "all":
        ucmd("imx04 bootkeep")
    commands.append("FB: Done")
    return "\n".join(commands) + "\n"


def bootloader_script(work):
    """Write only boot0 payload and PARTITION_CONFIG, on any existing layout."""
    image = work / "product.imx"
    size = image.stat().st_size
    commands = ["uuu_version 1.2.39", "SDP: dcd -f loader.imx",
                "SDP: write -f loader.imx -ivt 0", "SDP: jump -f loader.imx -ivt 0",
                f"FB: ucmd imx04 loaderguard {size:x}"]
    commands += [f"FB: ucmd imx04 loadersave {slot:x}" for slot in range(1024)]
    commands += ["FB: flash bootloader product.imx",
                 f"FB: ucmd imx04 verify 1 2 {size // 512:x} {sha256(image)}",
                 "FB: ucmd mmc partconf 1 1 1 0", "FB: ucmd imx04 bootconf 48"]
    commands += [f"FB: ucmd imx04 keep {slot:x}" for slot in range(1024)]
    commands.append("FB: Done")
    return "\n".join(commands) + "\n"


def main():
    parser = argparse.ArgumentParser(description="04 安全烧录：预检→目标确认→写入→读回比较")
    parser.add_argument("mode", nargs="?", choices=("bootloader", "all", "kernel", "dtb", "rootfs", "rtfs"))
    parser.add_argument("--all", dest="all_image", action="store_true", help="烧录单份整盘 system.sparse.img；等同 all")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--package", type=Path, help="完整系统下载包；仅 all/kernel/dtb/rootfs 使用")
    inputs.add_argument("--firmware", type=Path, help="U-Boot 构建产物目录；仅 bootloader 使用")
    parser.add_argument("--uuu", default="uuu", help="固定 UUU 可执行文件路径")
    parser.add_argument("--usb-path", help="存在多块板时显式指定 UUU USB 拓扑路径")
    parser.add_argument("--dry-run", action="store_true", help="仅主机预检，不枚举 USB、不下载、不写板")
    parser.add_argument("--log-dir", type=Path, help="证据目录，必须尚不存在；Snap 需能读取其路径")
    parser.add_argument("--wait", type=int, default=30, help="等待 ROM 出现时限")
    parser.add_argument("--stage-wait", type=int, default=60, help="下一 USB 阶段出现时限")
    parser.add_argument("--timeout", type=float, default=3600, help="整个 UUU 任务总时限，含读回和保护比较")
    args = parser.parse_args()
    if args.all_image:
        if args.mode is not None:
            parser.error("--all 与位置操作不可同时使用")
        args.mode = "all"
    if args.mode is None:
        parser.error("需要一个操作，整盘烧录请使用 --all")
    if min(args.wait, args.stage_wait, args.timeout) <= 0:
        parser.error("所有时限必须大于零")
    mode = "rootfs" if args.mode == "rtfs" else args.mode
    if mode == "bootloader" and args.package is not None:
        parser.error("bootloader 不需要系统包；使用 --firmware 或默认固件产物")
    if mode != "bootloader" and args.firmware is not None:
        parser.error("--firmware 仅用于 bootloader；系统操作使用 --package")
    required = firmware.BOOT_REQUIRED if mode == "bootloader" else REQUIRED
    uuu = shutil.which(args.uuu)
    if uuu is None:
        raise ValueError("主机没有指定的 UUU")
    uuu = str(Path(uuu).absolute())
    source = ((args.firmware or BUILD / "firmware/out") if mode == "bootloader"
              else (args.package or BUILD / "download")).resolve()
    sums = verify_sums(source, firmware.BUILD_REQUIRED if mode == "bootloader" else REQUIRED)
    logs = (args.log_dir or BSP / "artifacts" / ("flash-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))).resolve()
    logs.mkdir(parents=True, exist_ok=False)
    work = logs / "run"
    work.mkdir()
    print(f"证据目录：{logs}", flush=True)
    # UUU receives a private, checksum-verified snapshot, not changing source files.
    if mode == "bootloader":
        firmware.stage_build(source, work, BSP, sums)
    else:
        for name in sorted(REQUIRED):
            shutil.copyfile(source / name, work / name)
            if sha256(work / name) != sums[name]:
                raise ValueError(f"制作预检快照期间输入改变：{name}")
    write_sums(work)
    sums_digest = sha256(work / "SHA256SUMS")
    # General help contains the literal word 'error' in the -V description;
    # inspect its exit status and version, not transfer-failure text heuristics.
    version = run_uuu(uuu, ["-h"], work, logs / "uuu-version.log", 15, check_errors=False)
    match = re.search(r"libuuu_(\d+)\.(\d+)\.(\d+)", version)
    if match is None or tuple(map(int, match.groups())) < (1, 5, 21):
        raise ValueError("UUU 版本不能确认或低于预制 Sparse 所需的 1.5.21")
    report = {"operation": mode, "input": str(source), "uuu": uuu,
              "uuu_version": match.group(0)}
    if mode == "bootloader":
        text = bootloader_script(work)
        report.update({"boot0_offset": 1024, "boot0_bytes": (work / "product.imx").stat().st_size,
                       "boot_config": "boot0, BOOT_ACK=1, user area access",
                       "protected": "complete user area and boot0 outside payload"})
    else:
        config = layout(work / "layout.json")
        if config != layout(BSP / "layout.json"):
            raise ValueError("下载包布局与当前 uboot/layout.json 不同")
        firmware.validate(work, BSP)
        validate_files(work)
        with tempfile.TemporaryDirectory(prefix="check-", dir=logs) as scratch:
            system, rootfs = preflight_images(work, scratch, config)
        text = script_for(mode, work, config, system, rootfs)
        report.update({"layout": config, "system": system.summary(), "rootfs": rootfs.summary()})
    script = work / "task.uuu"
    script.write_text(text)
    script_digest = sha256(script)
    report["script_sha256"] = script_digest
    (logs / "preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    run_uuu(uuu, ["-dry", script.name], work, logs / "dry-run.log", 45, script=script, dry=True)
    if mode == "bootloader":
        print(f"\n操作：bootloader；MMC 1 boot0；字节范围 [0x400, {0x400 + report['boot0_bytes']:#x})，并设置 boot0 启动。")
        print("不写 user area、分区表、kernel/DTB/rootfs；对完整 user area 和 boot0 非镜像区域做写前/写后 hash 比较。")
        print("注意：仅部署固件不迁移旧系统布局。新 U-Boot 期待 p1 FAT/extlinux；旧系统可能停止在控制台，直到整机集成。")
    else:
        p1, p2 = config["p1"], config["p2"]
        print(f"\n操作：{mode}；MMC 1，p1 LBA {p1['start']}+{p1['sectors']}，p2 LBA {p2['start']}+{p2['sectors']}")
    if mode == "all":
        print("覆盖 user area 系统有效块、boot0 从 0x400 开始的产品 U-Boot，并设置 boot0 启动。")
        print(f"Sparse 统计：{system.summary()}；DONT_CARE 保留介质原数据，不是安全擦除。")
    elif mode != "bootloader":
        print("仅替换 p2 rootfs 有效块。" if mode == "rootfs" else "仅替换 p1 指定文件及必要 FAT 元数据。")
        print("保护比较：boot0、分区表、其他组件；同时保留 eMMC 启动配置。")
    if args.dry_run:
        print("主机预检及 UUU -dry 通过；没有枚举 USB 或访问板卡。板端容量/布局/空间检查待正式运行。")
        return
    if not sys.stdin.isatty():
        raise ValueError("正式写入必须在交互终端二次确认；无人值守仅允许 --dry-run")
    usb = select_rom(run_uuu(uuu, ["-lsusb"], work, logs / "usb.log", 15), args.usb_path)
    answer = input(f"目标 ROM USB 路径 {usb}。切到 USB 下载模式，输入 WRITE {usb} 确认：")
    if answer != f"WRITE {usb}":
        print("已取消，没有下载或写入板卡。")
        return
    if sha256(work / "SHA256SUMS") != sums_digest:
        raise ValueError("确认期间校验清单发生变化")
    verify_sums(work, required)
    if sha256(script) != script_digest:
        raise ValueError("确认期间 UUU 脚本发生变化")
    select_rom(run_uuu(uuu, ["-lsusb"], work, logs / "usb-confirmed.log", 15), usb)
    start = time.monotonic()
    run_uuu(uuu, ["-v", "-m", usb, "-t", str(args.wait), "-T", str(args.stage_wait), script.name],
            work, logs / "uuu.log", args.timeout, script=script)
    (logs / "result.json").write_text(json.dumps({"usb_path": usb, "operation": mode,
        "seconds": time.monotonic() - start, "write_and_readback": "passed",
        "cold_boot": "pending"}, indent=2) + "\n")
    print("写入、实际数据读回及保护比较命令全部通过；板端仍在 fastboot。")
    print("请切回 eMMC 模式并断电冷启动，保存串口日志；本结果不表示冷启动已验收。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中止；若写入已开始，必须检查日志及介质内容后再启动。", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
