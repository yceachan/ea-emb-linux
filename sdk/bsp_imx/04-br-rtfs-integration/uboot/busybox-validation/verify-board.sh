#!/bin/sh
# Read-only target checks. No mount, reboot, register, or persistent write.
set -eu
export LC_ALL=C

fail() { printf '[UBOOT BUSYBOX RUNTIME FAILED] %s\n' "$*" >&2; exit 1; }
[ "$#" -eq 1 ] || fail '用法：verify-uboot-busybox <最终下载包 boot.fat 的 SHA256>'
boot_sha=$1
[ "${#boot_sha}" -eq 64 ] || fail 'boot SHA256 长度不符'
case "$boot_sha" in *[!0-9a-f]*) fail 'boot SHA256 只接受小写十六进制' ;; esac
[ -f /etc/uboot-validation/expected.env ] || fail '不是 04 BusyBox 验收镜像'
. /etc/uboot-validation/expected.env

printf '\n=== U-Boot / BusyBox runtime evidence ===\n'
printf 'kernel: '; uname -a
[ "$(uname -r)" = "$KERNEL_RELEASE" ] || fail 'kernel release 与 03 基线不符'
printf 'cmdline: '; cat /proc/cmdline
case " $(cat /proc/cmdline) " in *' root=/dev/mmcblk1p2 '*) ;; *) fail 'root 参数不是 eMMC p2' ;; esac
printf 'PID 1: '; readlink /proc/1/exe
[ "$(readlink /proc/1/exe)" = /bin/busybox ] || fail 'PID 1 不是 BusyBox'
actual=$(sha256sum /bin/busybox | awk '{print $1}')
[ "$actual" = "$BUSYBOX_SHA256" ] || fail 'BusyBox ELF 与 03 基线不符'
printf 'busybox SHA256: %s\n' "$actual"
[ "$(cat /etc/build-info)" = "$(printf 'kernel=%s\nbusybox=%s' "$KERNEL_REVISION" "$BUSYBOX_REVISION")" ] ||
    fail '源码身份与 03 基线不符'
cat /etc/build-info

root_line=$(awk '$5 == "/" {print}' /proc/1/mountinfo)
[ "$(printf '%s\n' "$root_line" | awk '{print $3}')" = "$(cat /sys/class/block/mmcblk1p2/dev)" ] ||
    fail '实际根挂载设备不是 eMMC p2'
case "$root_line" in *' - ext4 '*) ;; *) fail '根文件系统不是 ext4' ;; esac
case ",$(printf '%s\n' "$root_line" | awk '{print $6}')," in *,rw,*) ;; *) fail '根文件系统不是 rw' ;; esac
printf 'root mount: %s\n' "$root_line"
[ "$(cat /sys/class/block/mmcblk1p1/start)" = "$P1_START" ] || fail 'p1 起点不符'
[ "$(cat /sys/class/block/mmcblk1p1/size)" = "$P1_SECTORS" ] || fail 'p1 容量不符'
[ "$(cat /sys/class/block/mmcblk1p2/start)" = "$P2_START" ] || fail 'p2 起点不符'
[ "$(cat /sys/class/block/mmcblk1p2/size)" = "$P2_SECTORS" ] || fail 'p2 容量不符'
printf 'p1: %s + %s sectors; p2: %s + %s sectors\n' "$P1_START" "$P1_SECTORS" "$P2_START" "$P2_SECTORS"
# Check the actual FAT partition, not stale /boot files inside p2. Linux VFAT
# support is irrelevant for this checksum; the known 03 kernel stays unchanged.
actual=$(sha256sum /dev/mmcblk1p1 | awk '{print $1}')
[ "$actual" = "$boot_sha" ] || fail '实际 p1 与最终下载包 boot.fat 不一致'
printf 'actual p1 SHA256: %s\n' "$actual"
if [ -f /sys/class/block/mmcblk1/device/cid ]; then
    printf 'eMMC CID: '; cat /sys/class/block/mmcblk1/device/cid
fi
printf '[UBOOT BUSYBOX RUNTIME PASSED]\n'
printf '此结果只证明运行时身份/布局/p1 内容；冷启动与自动引导需结合本轮完整串口日志。\n'
