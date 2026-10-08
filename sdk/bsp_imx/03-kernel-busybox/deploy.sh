#!/usr/bin/env bash
set -euo pipefail

dry_run=0
case "$#:${1:-}" in
    0:) ;;
    1:--dry-run) dry_run=1 ;;
    *) printf '用法：%s [--dry-run]\n' "$0" >&2; exit 2 ;;
esac

bsp=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work="$bsp/artifacts/emmc-rootfs"
for tool in sha256sum e2fsck uuu python3; do
    command -v "$tool" >/dev/null || { printf '缺少命令：%s\n' "$tool" >&2; exit 1; }
done
cd -- "$work"
logs=$(mktemp -d "$bsp/artifacts/deploy-$(TZ=Asia/Singapore date +%Y%m%d-%H%M%S)-XXXXXX")
printf '镜像目录：%s\n日志目录：%s\n' "$work" "$logs"

sha256sum --check --strict SHA256SUMS 2>&1 | tee "$logs/checksums.log"
[[ $(stat -c '%s' rootfs.ext4) == 1073741824 ]] || {
    printf 'rootfs.ext4 大小必须等于 p2 的 1 GiB。\n' >&2
    exit 1
}
e2fsck -fn rootfs.ext4 2>&1 | tee "$logs/fsck.log"

run_uuu() {
    local phase=$1
    shift
    python3 - "$phase" "$logs/$phase.log" "$@" <<'PY'
import errno
import os
from pathlib import Path
import pty
import re
import signal
import subprocess
import sys

phase, logfile, *options = sys.argv[1:]
# UUU buffers stdout when connected directly to tee. A PTY keeps its
# waiting messages and progress visible while preserving the full log.
master, slave = pty.openpty()
try:
    process = subprocess.Popen(['uuu', *options, 'emmc-rootfs.uuu'],
                               stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                               start_new_session=True)
finally:
    os.close(slave)
try:
    with Path(logfile).open('wb') as log:
        while True:
            try:
                data = os.read(master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not data:
                break
            log.write(data)
            log.flush()
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    status = process.wait()
finally:
    os.close(master)
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
if status:
    raise SystemExit(f'UUU {phase} 退出码 {status}，查看 {logfile}')
# The Snap launcher may return zero even when UUU reports failure.
text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', Path(logfile).read_text())
expected = [line.strip() for line in Path('emmc-rootfs.uuu').read_text().splitlines()
            if line.startswith('FB:')]
if re.search(r'\b(?:Error|Fail|Failed)\b', text, re.I):
    raise SystemExit(f'UUU 报告失败，查看 {logfile}')
if phase == 'dry-run':
    actual = [line.strip() for line in text.splitlines() if line.startswith('FB:')]
else:
    steps = re.findall(r'Start Cmd:([^\r\n]+)(.*?)(?=Start Cmd:|\Z)', text, re.S)
    actual = [command.strip() for command, _ in steps]
    if not steps or not all(re.search(r'\bOkay\b', body) for _, body in steps):
        raise SystemExit(f'UUU 缺少完整成功记录，查看 {logfile}')
if actual != expected:
    raise SystemExit(f'UUU 命令记录不完整，查看 {logfile}')
PY
}

run_uuu dry-run -dry
printf '\n预检通过；尚未下载或写入板卡。\n'
if (( dry_run )); then
    exit 0
fi

[[ -t 0 ]] || { printf '烧录确认需要交互终端；只检查请使用 --dry-run。\n' >&2; exit 1; }
printf '\n即将覆盖 eMMC user area p2（LBA 1028098，2097152 扇区）。\n'
printf '请在目标板的 02 U-Boot 控制台执行：fastboot usb 0\n'
read -r -p '板卡就绪后按 Enter 开始烧录，输入其他内容取消：' answer || exit 1
if [[ -n $answer ]]; then
    printf '已取消，未烧录。\n'
    exit 0
fi

printf '\n启动 UUU；等待 USB fastboot 设备最多 30 秒，实时输出与日志同步。\n'
run_uuu flash -v -t 30
printf '\nUUU 写入命令全部成功；请在串口按 Ctrl-C 返回 U-Boot，按 DEPLOY.md 手工启动验收。\n'
