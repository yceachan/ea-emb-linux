#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 || ( $1 != configure && $1 != dtb && $1 != build ) ]]; then
    printf '用法：%s configure|dtb|build 新构建目录\n' "$0" >&2
    exit 2
fi
bsp=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=$(cd -- "$bsp/../../../.." && pwd)
work=$(realpath -m -- "$2")
source "$repo/profile/prebuilt.env"
read -r revision < "$bsp/base-revision"
src="$work/src"
out="$work/out"
dtb=nxp/imx/imx6ull-100ask-pro.dtb

if [[ $1 == configure ]]; then
    mkdir -- "$work"
    mkdir -- "$src" "$out"
    git -C "$repo/sdk/vendor_mainline/linux-7.2.9" archive "$revision" |
        tar -x -C "$src"
    cp -a -- "$bsp/overlay/." "$src/"
    git -C "$src" apply "$bsp/register-board.patch"
    make -C "$src" O="$out" imx_v6_v7_defconfig 2>&1 | tee "$work/configure.log"
    "$src/scripts/kconfig/merge_config.sh" -m -O "$out" \
        "$out/.config" "$bsp/board.config" 2>&1 | tee "$work/merge.log"
    make -C "$src" O="$out" olddefconfig 2>&1 | tee "$work/olddefconfig.log"
    python3 - "$bsp/board.config" "$out/.config" <<'PY'
import sys
from pathlib import Path
expected = [line for line in Path(sys.argv[1]).read_text().splitlines()
            if line.startswith('CONFIG_') or line.startswith('# CONFIG_')]
actual = set(Path(sys.argv[2]).read_text().splitlines())
missing = [line for line in expected if line not in actual]
if missing:
    raise SystemExit('内核配置未满足板级输入：\n' + '\n'.join(missing))
PY
    printf '%s\n' "$revision" > "$out/source-revision"
    (
        cd -- "$bsp"
        sha256sum base-revision board.config register-board.patch build.sh
        find overlay -type f -print0 | sort -z | xargs -0 sha256sum
    ) > "$out/bsp-inputs.sha256"
elif [[ $1 == dtb ]]; then
    test -f "$out/.config"
    make -C "$src" O="$out" W=1 "$dtb" 2>&1 | tee "$work/dtb.log"
else
    test -f "$out/.config"
    # Core/peripheral board drivers are built in. No modules are deployed yet.
    make -C "$src" O="$out" -j12 zImage "$dtb" 2>&1 | tee "$work/build.log"
    (
        cd -- "$out"
        sha256sum arch/arm/boot/zImage "arch/arm/boot/dts/$dtb" \
            .config source-revision bsp-inputs.sha256 > SHA256SUMS
    )
fi
