#!/usr/bin/env bash
set -euo pipefail
umask 022

if [[ $# != 2 || ( $1 != configure && $1 != build ) ]]; then
    printf '用法：%s configure|build 新构建目录\n' "$0" >&2
    exit 2
fi
bsp=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
repo=$(cd -- "$bsp/../../.." && pwd)
work=$(realpath -m -- "$2")
source "$repo/profile/prebuilt.env"
read -r revision < "$bsp/rootfs/base-revision"
src="$work/src"
out="$work/out"

if [[ $1 == configure ]]; then
    mkdir -- "$work"
    mkdir -- "$src" "$out"
    git -C "$repo/sdk/vendor_mainline/busybox-1.36.1" archive "$revision" |
        tar -x -C "$src"
    make -C "$src" O="$out" CROSS_COMPILE="$CROSS_COMPILE" allnoconfig \
        > "$work/allnoconfig.log" 2>&1
    python3 - "$bsp/rootfs/board.config" "$out/.config" <<'PY'
from pathlib import Path
import re, sys
fragment = Path(sys.argv[1]).read_text().splitlines()
keys = {line.split('=', 1)[0] for line in fragment if line.startswith('CONFIG_')}
config = Path(sys.argv[2])
lines = [line for line in config.read_text().splitlines()
         if re.sub(r'^# (CONFIG_\w+) is not set$', r'\1', line).split('=', 1)[0] not in keys]
config.write_text('\n'.join(lines + fragment) + '\n')
PY
    # This older Kconfig resets seeded booleans in allnoconfig. Resolve the
    # explicit choices afterwards; new optional symbols retain their defaults.
    make -C "$src" O="$out" CROSS_COMPILE="$CROSS_COMPILE" oldconfig \
        < /dev/null > "$work/configure.log" 2>&1
    python3 - "$bsp/rootfs/board.config" "$out/.config" <<'PY'
from pathlib import Path
import sys
expected = Path(sys.argv[1]).read_text().splitlines()
actual = set(Path(sys.argv[2]).read_text().splitlines())
missing = [line for line in expected if line.startswith('CONFIG_') and line not in actual]
if missing:
    raise SystemExit('BusyBox 配置未满足输入：\n' + '\n'.join(missing))
PY
    printf '%s\n' "$revision" > "$out/source-revision"
    (
        cd -- "$bsp"
        sha256sum rootfs/build.sh rootfs/board.config rootfs/base-revision
    ) > "$out/bsp-inputs.sha256"
else
    (cd -- "$bsp"; sha256sum -c "$out/bsp-inputs.sha256")
    make -C "$src" O="$out" CROSS_COMPILE="$CROSS_COMPILE" -j12 \
        2>&1 | tee "$work/build.log"
    "${CROSS_COMPILE}readelf" -h -l -d "$out/busybox" > "$out/elf-info.txt"
    grep -q 'Machine:.*ARM' "$out/elf-info.txt"
    grep -q 'hard-float ABI' "$out/elf-info.txt"
    if grep -Eq 'INTERP|\(NEEDED\)' "$out/elf-info.txt"; then
        printf 'BusyBox 仍依赖动态链接器或共享库\n' >&2
        exit 1
    fi
    make -C "$src" O="$out" CROSS_COMPILE="$CROSS_COMPILE" \
        CONFIG_PREFIX="$work/install" install 2>&1 | tee "$work/install.log"
    (
        cd -- "$out"
        sha256sum busybox .config busybox.links source-revision bsp-inputs.sha256 \
            elf-info.txt > SHA256SUMS
    )
fi
