#!/usr/bin/env python3
"""Compile board commands against memory-backed MMC; never access hardware."""
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=False)
native = Path(__file__).resolve().parent / 'native'
source = native.parents[1] / 'overlay/board/100ask/imx6ull/uuf.c'
shim = args.output / 'shim'
headers = ['command.h', 'env.h', 'fastboot.h', 'fastboot-internal.h', 'fs.h',
           'ext4fs.h', 'malloc.h', 'memalign.h', 'mmc.h', 'part.h', 'vsprintf.h',
           'asm/unaligned.h', 'u-boot/sha256.h', 'linux/delay.h']
for name in headers:
    path = shim / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#include "{native / "board_mock.h"}"\n')
executable = args.output / 'board-test'
subprocess.run(['cc', '-O1', '-Wall', '-Wextra', '-Werror',
                '-Wno-unused-function', '-Wno-unused-parameter',
                '-Wno-deprecated-declarations', '-I' + str(shim), '-I' + str(native),
                f'-DUUF_BOARD_SOURCE="{source}"', native / 'board.c',
                '-lcrypto', '-o', executable], check=True)
subprocess.run([executable], check=True)
