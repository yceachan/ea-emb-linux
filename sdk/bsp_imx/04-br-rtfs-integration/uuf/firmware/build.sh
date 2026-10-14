#!/usr/bin/env bash
set -euo pipefail
[[ $# == 2 && ( $1 == configure || $1 == check || $1 == build ) ]] || {
    echo "用法：UBOOT_SOURCE=源码Git库 CROSS_COMPILE=工具链前缀 $0 configure|check|build 构建目录" >&2; exit 2;
}
: "${CROSS_COMPILE:?提供交叉工具链前缀}"
bsp=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
work=$(realpath -m -- "$2")
read -r revision < "$bsp/base-revision"
inputs() {
    (cd "$bsp"; sha256sum base-revision register-board.patch ext4-io.patch build.sh;
     find overlay -type f -print0 | sort -z | xargs -0 sha256sum)
}
if [[ $1 == configure ]]; then
    : "${UBOOT_SOURCE:?提供上游 U-Boot Git 库路径}"
    git -C "$UBOOT_SOURCE" cat-file -e "$revision^{commit}"
    mkdir -p -- "$(dirname -- "$work")"
    mkdir -- "$work"
    mkdir -- "$work/src" "$work/out"
    git -C "$UBOOT_SOURCE" archive "$revision" | tar -x -C "$work/src"
    cp -a -- "$bsp/overlay/." "$work/src/"
    patch --batch --forward -d "$work/src" -p1 < "$bsp/register-board.patch"
    patch --batch --forward -d "$work/src" -p1 < "$bsp/ext4-io.patch"
    make -C "$work/src" O="$work/out" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" 100ask_imx6ull_defconfig 2>&1 | tee "$work/configure.log"
    (cd "$work/src"; find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$work/out/source-tree.sha256"
    inputs > "$work/out/bsp-inputs.sha256"
    printf '%s\n' "$revision" > "$work/out/source-revision"
    (cd "$work/out"; sha256sum .config > config.sha256)
else
    cmp -- "$work/out/bsp-inputs.sha256" <(inputs) || { echo '输入变化，须在新目录重新 configure' >&2; exit 1; }
    (cd "$work/src"; find . -type f -print0 | sort -z | xargs -0 sha256sum) > "$work/out/source-tree.current.sha256"
    cmp -- "$work/out/source-tree.sha256" "$work/out/source-tree.current.sha256" || {
        rm -f -- "$work/out/source-tree.current.sha256"
        echo 'U-Boot 源码树变化，须在新目录重新 configure' >&2; exit 1;
    }
    rm -- "$work/out/source-tree.current.sha256"
    (cd "$work/out"; sha256sum -c config.sha256)
    if [[ $1 == check ]]; then
        make -C "$work/src" O="$work/out" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" -j12 \
            board/100ask/imx6ull/imx6ull.o board/100ask/imx6ull/uuf.o \
            fs/ext4/dev.o fs/ext4/ext4_common.o fs/ext4/ext4_write.o fs/ext4/ext4_journal.o 2>&1 | tee "$work/check.log"
    else
        make -C "$work/src" O="$work/out" ARCH=arm CROSS_COMPILE="$CROSS_COMPILE" -j12 all 2>&1 | tee "$work/build.log"
        "$work/out/tools/mkimage" -l "$work/out/u-boot-dtb.imx" | tee "$work/out/image-info.txt"
        test "$(stat -c %s "$work/out/u-boot-dtb.imx")" -le $((0x100000 - 0x400))
        (cd "$work/out"; sha256sum u-boot-dtb.imx .config source-revision bsp-inputs.sha256 source-tree.sha256 image-info.txt > SHA256SUMS)
        mkdir -- "$work/release"
        cp -- "$work/out/u-boot-dtb.imx" "$work/out/.config" "$work/out/source-revision" \
            "$work/out/bsp-inputs.sha256" "$work/out/source-tree.sha256" \
            "$work/out/image-info.txt" "$work/out/SHA256SUMS" "$work/release/"
    fi
fi
