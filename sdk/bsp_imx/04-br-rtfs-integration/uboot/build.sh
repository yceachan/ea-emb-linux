#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 && ( $1 == configure || $1 == build ) ]] || {
    printf '用法：%s configure|build\n' "$0" >&2; exit 2;
}
bsp=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
repo=$(cd -- "$bsp/../../.." && pwd)
work="$bsp/build/uboot/firmware"
src="$work/src"
out="$work/out"
source "$repo/profile/prebuilt.env"
read -r revision < "$bsp/uboot/base-revision"
upstream=${UBOOT_SOURCE:-$repo/sdk/vendor_mainline/uboot-2026.07}
inputs() {
    (
        cd -- "$bsp/uboot"
        sha256sum base-revision register-board.patch build.sh
        find overlay -type f -print0 | sort -z | xargs -0 sha256sum
    )
}
if [[ $1 == configure ]]; then
    git -C "$upstream" cat-file -e "$revision^{commit}"
    mkdir -p -- "$bsp/build/uboot"
    mkdir -- "$work"
    mkdir -- "$src" "$out"
    git -C "$upstream" archive "$revision" | tar -x -C "$src"
    cp -a -- "$bsp/uboot/overlay/." "$src/"
    patch --batch --forward -d "$src" -p1 < "$bsp/uboot/register-board.patch"
    make -C "$src" O="$out" 100ask_imx6ull_defconfig 2>&1 | tee "$work/configure.log"
    inputs > "$out/bsp-inputs.sha256"
    printf '%s\n' "$revision" > "$out/source-revision"
    sha256sum "$out/.config" > "$out/config.sha256"
    printf '\n配置完成；完整构建由开发者执行：\n%s build\n' "$0"
else
    test -f "$out/.config"
    cmp -- "$out/bsp-inputs.sha256" <(inputs) || {
        printf '板级输入已改变，禁止复用旧快照；将 build/uboot/firmware 移走后重新 configure。\n' >&2
        exit 1
    }
    sha256sum -c "$out/config.sha256"
    make -C "$src" O="$out" -j12 all 2>&1 | tee "$work/build.log"
    "$out/tools/mkimage" -l "$out/u-boot-dtb.imx" | tee "$out/image-info.txt"
    test "$(stat -c %s "$out/u-boot-dtb.imx")" -le $((0x100000 - 0x400))
    (
        cd -- "$out"
        sha256sum u-boot-dtb.imx .config source-revision bsp-inputs.sha256 image-info.txt > SHA256SUMS
    )
    printf '\n04 固件与构建记录：%s\n' "$out"
fi
