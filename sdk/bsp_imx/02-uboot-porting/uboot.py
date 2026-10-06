#!/usr/bin/env python3
"""Run this board's UUU scripts and serial console from one host command."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import subprocess
import sys
import termios
import time
import tty

import serial


BSP = Path(__file__).resolve().parent
ANSI = re.compile(rb"\x1b\[[0-?]*[ -/]*[@-~]")


def plain(data):
    return ANSI.sub(b"", data).decode("utf-8", errors="replace")


def uuu_failed(data):
    # The installed Snap launcher can return zero after UUU reports failure.
    return re.search(r"\b(?:Error|Fail)\b", plain(data)) is not None


def checked_command(command, cwd, logfile):
    result = subprocess.run(
        command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=15,
    )
    logfile.write_bytes(result.stdout)
    if result.returncode or uuu_failed(result.stdout):
        raise RuntimeError(f"命令失败，查看 {logfile}\n{plain(result.stdout)}")
    return result.stdout


def rom_path(uuu, work, logs):
    output = checked_command([uuu, "-lsusb"], work, logs / "usb.log")
    paths = []
    for line in plain(output).splitlines():
        fields = line.split()
        if len(fields) >= 5 and fields[1] == "MX6ULL":
            if (fields[2].rstrip(":") == "SDP"
                    and int(fields[3], 16) == 0x15A2
                    and int(fields[4], 16) == 0x0080):
                paths.append(fields[0])
    if len(paths) != 1:
        raise RuntimeError(
            f"识别到 {len(paths)} 个 i.MX6ULL ROM 下载设备，需要恰好一个。"
            "将目标板切到 ROM USB 下载模式，并连接 OTG1。"
        )
    return paths[0]


def steps_complete(output, script):
    expected = [line.strip() for line in script.read_text().splitlines()
                if line.startswith(("SDP:", "FB:"))]
    steps = re.findall(
        r"Start Cmd:([^\r\n]+)(.*?)(?=Start Cmd:|\Z)", plain(output), re.S,
    )
    return ([command.strip() for command, _ in steps] == expected
            and all(re.search(r"\bOkay\b", body) for _, body in steps))


def stop_process(process):
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def serial_output(port, logfile):
    data = port.read(port.in_waiting or 1)
    if data:
        logfile.write(data)
        logfile.flush()
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    return data


def transfer(uuu, work, script, usbpath, port, serial_log, logs, mode, timeout):
    port.reset_input_buffer()
    output = bytearray()
    received = bytearray()
    ready = False
    fastboot_sent = False
    deadline = time.monotonic() + timeout
    exit_deadline = None
    image_size = (work / "u-boot-dtb.imx").stat().st_size
    comparison = f"Total of {image_size} byte(s) were the same".encode()
    process = subprocess.Popen(
        [uuu, "-v", "-m", usbpath, script.name], cwd=work,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        with selectors.DefaultSelector() as poller, (logs / "uuu.log").open("wb") as uuu_log:
            poller.register(port.fileno(), selectors.EVENT_READ, "serial")
            poller.register(process.stdout, selectors.EVENT_READ, "uuu")
            output_open = True
            while True:
                for key, _ in poller.select(timeout=0.1):
                    if key.data == "serial":
                        received.extend(serial_output(port, serial_log))
                    else:
                        data = os.read(process.stdout.fileno(), 8192)
                        if data:
                            output.extend(data)
                            uuu_log.write(data)
                            uuu_log.flush()
                        else:
                            poller.unregister(process.stdout)
                            output_open = False

                if uuu_failed(output):
                    raise RuntimeError(f"UUU 报告失败，查看 {logs / 'uuu.log'}")

                # Only a fresh banner from this ROM download unlocks automation.
                if (not ready and b"U-Boot " in received
                        and b"Board: 100ask i.MX6ULL Pro" in received
                        and received.rstrip().endswith(b"=>")):
                    ready = True
                    if mode == "emmc":
                        port.write(b"fastboot usb 0\r")
                        fastboot_sent = True

                if process.poll() is not None and not output_open:
                    if exit_deadline is None:
                        # UART adapter delivery can lag the final USB response.
                        exit_deadline = time.monotonic() + 1
                    if ready and (mode == "ram" or comparison in received):
                        break
                    if time.monotonic() >= exit_deadline:
                        break
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"操作超过 {timeout:g} 秒，查看 {logs}")

            if process.returncode or not steps_complete(output, script):
                raise RuntimeError(f"UUU 未完成全部命令，查看 {logs / 'uuu.log'}")
            if not ready:
                raise RuntimeError("没有收到本轮 U-Boot 板名和控制台提示符。")
            if mode == "emmc" and comparison not in received:
                raise RuntimeError("没有收到完整镜像的逐字节比较成功记录。")
    finally:
        stop_process(process)
        process.stdout.close()
        if fastboot_sent:
            # FB: Done ends the host script; Ctrl-C releases the board console.
            port.write(b"\x03")

    if fastboot_sent:
        prompt = bytearray()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            prompt.extend(serial_output(port, serial_log))
            if prompt.rstrip().endswith(b"=>"):
                break
            time.sleep(0.02)
        else:
            raise RuntimeError("写入与比较已通过，但退出 fastboot 后没有收到控制台提示符。")


def console(port, serial_log):
    if not sys.stdin.isatty():
        raise RuntimeError("交互控制台需要终端。自动运行时使用 --no-console。")
    print("\n控制台已连接。Ctrl-] 退出脚本；Ctrl-C 发送给板卡。", flush=True)
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        with selectors.DefaultSelector() as poller:
            poller.register(fd, selectors.EVENT_READ, "input")
            poller.register(port.fileno(), selectors.EVENT_READ, "serial")
            while True:
                for key, _ in poller.select():
                    if key.data == "serial":
                        serial_output(port, serial_log)
                    else:
                        data = os.read(fd, 1024)
                        if not data:
                            return
                        command, separator, _ = data.partition(b"\x1d")
                        if command:
                            # Enter sends CR to the U-Boot command interpreter.
                            port.write(command.replace(b"\n", b"\r"))
                        if separator:
                            return
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        print()


def main():
    parser = argparse.ArgumentParser(description="本板 UUU 下载、eMMC 烧录与串口控制台")
    parser.add_argument("mode", choices=("ram", "emmc", "console"))
    parser.add_argument("--artifacts", type=Path, default=BSP / "artifacts")
    parser.add_argument("--serial", default="/dev/ttyACM0")
    parser.add_argument("--baudrate", type=int, default=1500000)
    parser.add_argument("--timeout", type=float, default=60, help="下载或烧录总时限，秒")
    parser.add_argument("--log-dir", type=Path, help="新日志目录，必须尚不存在")
    parser.add_argument("--dry-run", action="store_true", help="只核对产物与 UUU 脚本")
    parser.add_argument("--no-console", action="store_true", help="完成后退出，不进入交互控制台")
    args = parser.parse_args()
    if args.timeout <= 0 or args.baudrate <= 0:
        parser.error("时限与波特率必须大于零")
    if args.mode == "console" and (args.dry_run or args.no_console):
        parser.error("console 模式不接受 --dry-run 或 --no-console")
    if not args.dry_run and not args.no_console and not sys.stdin.isatty():
        parser.error("交互控制台需要终端。自动运行时使用 --no-console")

    logs = (args.log_dir or BSP / "logs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")).resolve()
    logs.mkdir(parents=True, exist_ok=False)
    print(f"日志目录：{logs}", flush=True)
    work = args.artifacts.resolve()
    with (logs / "serial.log").open("wb") as serial_log:
        if args.mode != "console":
            uuu = shutil.which("uuu")
            if uuu is None:
                raise RuntimeError("主机没有 uuu 命令。")
            script = work / ("ram-boot.uuu" if args.mode == "ram" else "emmc-flash.uuu")
            checked_command(["sha256sum", "--check", "--strict", "SHA256SUMS"], work, logs / "checksums.log")
            checked_command([uuu, "-dry", script.name], work, logs / "dry-run.log")
            if args.dry_run:
                print("产物校验与 UUU 预检通过，没有访问串口或写入板卡。")
                return
            usbpath = rom_path(uuu, work, logs)
            print(f"目标 ROM USB 路径：{usbpath}", flush=True)

        with serial.Serial(
            args.serial, args.baudrate, timeout=0, write_timeout=2,
            exclusive=True, rtscts=False, xonxoff=False, dsrdtr=False,
        ) as port:
            if args.mode != "console":
                transfer(uuu, work, script, usbpath, port, serial_log, logs, args.mode, args.timeout)
                print("\nRAM 下载与控制台验证通过。" if args.mode == "ram"
                      else "\neMMC 写入与全量读回比较通过。", flush=True)
            if not args.no_console:
                console(port, serial_log)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n操作已中止。若写入已开始，先检查日志和 eMMC 内容。", file=sys.stderr)
        sys.exit(130)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"错误：{error}", file=sys.stderr)
        sys.exit(1)
