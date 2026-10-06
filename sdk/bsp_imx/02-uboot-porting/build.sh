#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 || ( $1 != configure && $1 != build ) ]]; then
    printf '用法：%s configure|build 构建目录\n' "$0" >&2
    exit 2
fi

bsp=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$bsp/../../.." && pwd)
work=$(realpath -m -- "$2")
source "$repo/profile/prebuilt.env"
read -r revision < "$bsp/base-revision"
src="$work/src"
out="$work/out"

if [[ $1 == configure ]]; then
    # A fresh snapshot isolates this board from the existing EVK build.
    mkdir -- "$work"
    mkdir -- "$src" "$out"
    git -C "$repo/sdk/vendor_mainline/uboot-2026.07" archive "$revision" |
        tar -x -C "$src"
    cp -a -- "$bsp/overlay/." "$src/"
    git -C "$src" apply "$bsp/register-board.patch"
    make -C "$src" O="$out" 100ask_imx6ull_ram_defconfig \
        2>&1 | tee "$work/configure.log"
    printf '%s\n' "$revision" > "$out/source-revision"
    (
        cd -- "$bsp"
        sha256sum base-revision register-board.patch ram-boot.uuu emmc-flash.uuu build.sh
        find overlay -type f -print0 | sort -z | xargs -0 sha256sum
    ) > "$out/bsp-inputs.sha256"
    cp -- "$bsp/ram-boot.uuu" "$out/ram-boot.uuu"
    cp -- "$bsp/emmc-flash.uuu" "$out/emmc-flash.uuu"
    printf '\n配置完成。完整构建由开发者执行：\n%s build %s\n' "$0" "$work"
else
    test -f "$out/.config"
    make -C "$src" O="$out" -j4 all 2>&1 | tee "$work/build.log"
    "$out/tools/mkimage" -l "$out/u-boot-dtb.imx" |
        tee "$out/image-info.txt"
    # Match the raw fastboot region, which starts at 1 KiB and ends at 1 MiB.
    test "$(stat -c %s "$out/u-boot-dtb.imx")" -le $((0x100000 - 0x400))
    (
        cd -- "$out"
        sha256sum u-boot-dtb.imx u-boot.dtb .config ram-boot.uuu emmc-flash.uuu \
            source-revision bsp-inputs.sha256 > SHA256SUMS
    )
    # The installed uuu snap has a private /tmp. Deliver its inputs under home.
    mkdir -p -- "$bsp/artifacts"
    cp -- "$out/u-boot-dtb.imx" "$out/u-boot.dtb" "$out/.config" \
        "$out/ram-boot.uuu" "$out/emmc-flash.uuu" "$out/source-revision" "$out/bsp-inputs.sha256" \
        "$out/SHA256SUMS" "$out/image-info.txt" "$bsp/artifacts/"
    printf '\nRAM 下载镜像：%s/artifacts/u-boot-dtb.imx\n' "$bsp"
fi
