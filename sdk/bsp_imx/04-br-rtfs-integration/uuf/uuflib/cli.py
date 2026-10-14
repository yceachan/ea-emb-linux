"""CLI and JSON Lines RPC share argument validation and operation dispatch."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import math
import os
from pathlib import Path
import secrets
import signal
import struct
import subprocess
import sys
import tarfile

from .backend import Session
from .model import BOARD, targets, make_mbr, json_file
from .package import component, pack, unpack
from .rootfs import payload_size, prepare


def integer(value):
    return int(value, 0)


def emit_terminal(kind, data):
    if kind == 'log':
        sys.stdout.write(data['text'])
        sys.stdout.flush()
    else:
        print('[' + kind + '] ' + json.dumps(data, ensure_ascii=False, indent=2), flush=True)


def confirm_terminal(phase, plan):
    if not sys.stdin.isatty():
        raise ValueError('正式操作需要交互终端或 GUI；离线检查使用 --dry-run')
    token = 'CONTINUE' if phase == 'host-plan' else 'WRITE ' + plan['actual']['cid'][-8:]
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if input(f'{phase}：输入 {token} 确认，其他输入取消：').strip() != token:
        raise ValueError('操作已取消')


def confirm_rpc(emit, phase, plan):
    token = secrets.token_hex(16)
    emit('confirmation', {'phase': phase, 'token': token, 'plan': plan})
    if json.loads(sys.stdin.readline()) != {'confirm': token}:
        raise ValueError('操作已取消')


def create_layout(r):
    component('kernel', r['kernel'])
    component('dtb', r['dtb'])
    if any(type(r[k]) is not int or r[k] < 0 for k in ('kernel_reserve', 'rtfs_reserve')):
        raise ValueError('预留量必须为非负字节数')
    if r['disk_sectors'] is not None and not 0 < r['disk_sectors'] <= 0xffffffff:
        raise ValueError('预期设备扇区数非法')
    mapping = targets({'board': BOARD,
                       'kernel': {'partition': r['kernel_part'], 'path': r['kernel_path']},
                       'dtb': {'partition': r['kernel_part'], 'path': r['dtb_path']},
                       'rtfs': {'partition': r['rtfs_part']}})
    def capacity(payload, reserve):
        value = payload + reserve + 16 * 1024 * 1024
        return max(32 * 1024 * 1024, (value + 1024 * 1024 - 1) // (1024 * 1024) * (1024 * 1024))
    kernel_size = capacity(Path(r['kernel']).stat().st_size + Path(r['dtb']).stat().st_size + 8 * 4096, r['kernel_reserve'])
    rtfs_size = capacity(payload_size(r['rootfs']), r['rtfs_reserve'])
    data = make_mbr(kernel_size, rtfs_size, mapping, r['signature'], r['disk_sectors'])
    output = Path(r['output']).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / 'mbr.bin').write_bytes(data)
    (output / 'targets.json').write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + '\n')
    boot = {'label': r['label'], 'kernel': r['kernel_path'], 'dtb': r['dtb_path'], 'append': r['append']}
    (output / 'boot.json').write_text(json.dumps(boot, ensure_ascii=False, indent=2) + '\n')
    return {'mbr': str(output / 'mbr.bin'), 'targets': str(output / 'targets.json'),
            'boot': str(output / 'boot.json'), 'kernel_bytes': kernel_size, 'rtfs_bytes': rtfs_size,
            'device_capacity': 'supplied' if r['disk_sectors'] else 'checked-after-loader-startup'}


def dispatch(r, emit, confirm):
    op = r['operation']
    if op in ('deploy', 'update', 'inspect', 'erase'):
        return Session(r, emit, confirm).execute()
    if op == 'layout':
        result = create_layout(r)
    elif op == 'pack':
        result = pack(r)
    elif op == 'unpack':
        checked = unpack(r['archive'], r['output'])
        result = {'bundle': str(checked['folder'].resolve()), 'manifest': checked['manifest'],
                  'images': checked['images']}
    elif op == '_rootfs':
        result = prepare(json_file(r['request']))
    else:
        raise ValueError(f'未知操作：{op}')
    emit('result', result)
    return result


def parser():
    p = argparse.ArgumentParser(prog='uuf', description='i.MX6ULL：布局、制像、归档、探测、部署与独立更新')
    sub = p.add_subparsers(dest='operation', required=True)
    for op in ('deploy', 'update', 'inspect', 'erase'):
        s = sub.add_parser(op)
        s.add_argument('--firmware', default=os.environ.get('UUF_FIRMWARE'))
        s.add_argument('--firmware-target')
        s.add_argument('--uuu', default=os.environ.get('UUF_UUU', 'uuu'))
        s.add_argument('--usb-path')
        s.add_argument('--log-dir')
        s.add_argument('--timeout', type=float, default=3600)
        s.add_argument('--dry-run', action='store_true')
        s.add_argument('--kernel-part', type=int, choices=range(5), default=0)
        s.add_argument('--label')
        if op == 'deploy':
            s.add_argument('--archive', required=True)
        if op in ('update', 'erase'):
            s.add_argument('--targets')
            s.add_argument('--expected-mbr', help='独立操作的预期 MBR，只核对、不写入')
        if op == 'update':
            s.add_argument('--uboot', action='store_true')
            for name in ('kernel', 'dtb', 'rtfs'):
                s.add_argument('--' + name)
        if op == 'inspect':
            s.add_argument('--with-boot', action='store_true', help='明确要求读取 extlinux；基础探测支持空盘')
        if op == 'erase':
            s.add_argument('--region', choices=('firmware', 'kernel', 'rtfs'), required=True)
            s.add_argument('--offset', type=integer)
            s.add_argument('--bytes', type=integer)
    s = sub.add_parser('layout', help='按载荷和预留量生成 MBR 与独立描述')
    for name in ('kernel', 'dtb', 'rootfs', 'kernel-path', 'dtb-path', 'output'):
        s.add_argument('--' + name, required=True)
    s.add_argument('--kernel-part', type=int, choices=range(1, 5), default=1)
    s.add_argument('--rtfs-part', type=int, choices=range(1, 5), default=2)
    s.add_argument('--signature')
    s.add_argument('--disk-sectors', type=integer)
    s.add_argument('--label', default='imx')
    s.add_argument('--append', default='console=ttymxc0,1500000')
    s.add_argument('--kernel-reserve', type=integer, default=32 * 1024 * 1024)
    s.add_argument('--rtfs-reserve', type=integer, default=64 * 1024 * 1024)
    s = sub.add_parser('pack', help='新建两个 ext4、Sparse 和完整部署归档')
    for name in ('firmware', 'kernel', 'dtb', 'rootfs', 'mbr', 'targets', 'boot', 'output'):
        s.add_argument('--' + name, required=True)
    s.add_argument('--firmware-target')
    s.add_argument('--archive')
    s.add_argument('--linux-boot-device', help='03 BusyBox /boot 挂载准备；Linux 设备号必须实测')
    s.add_argument('--kernel-reserve', type=integer, default=32 * 1024 * 1024)
    s.add_argument('--rtfs-reserve', type=integer, default=64 * 1024 * 1024)
    s = sub.add_parser('unpack')
    s.add_argument('--archive', required=True)
    s.add_argument('--output', required=True)
    return p


def rpc_arguments():
    line = sys.stdin.readline()
    if not line:
        raise ValueError('RPC 请求为空')
    request = json.loads(line)
    if not isinstance(request, dict) or not isinstance(request.get('operation'), str):
        raise ValueError('RPC 请求必须为含 operation 的 JSON 对象')
    parsed = parser()
    commands = next(a for a in parsed._actions if isinstance(a, argparse._SubParsersAction)).choices
    if request['operation'] not in commands:
        raise ValueError('RPC 操作不存在')
    actions = {option[2:].replace('-', '_'): a for a in commands[request['operation']]._actions
               for option in a.option_strings if option.startswith('--')}
    if not set(request) <= set(actions) | {'operation'}:
        raise ValueError('RPC 请求含该操作不支持的字段')
    argv = [request['operation']]
    for key, value in request.items():
        if key == 'operation' or value is None:
            continue
        flag = isinstance(actions[key], argparse._StoreTrueAction)
        if flag and type(value) is not bool or not flag and (isinstance(value, bool) or not isinstance(value, (str, int, float))):
            raise ValueError(f'RPC 字段类型不正确：{key}')
        if flag and value is False:
            continue
        argv.append('--' + key.replace('_', '-'))
        if value is not True:
            argv.append(str(value))
    error, output = StringIO(), StringIO()
    try:
        with redirect_stderr(error), redirect_stdout(output):
            return vars(parsed.parse_args(argv))
    except SystemExit as e:
        detail = next((l for l in reversed(error.getvalue().splitlines()) if l.strip()), '')
        raise ValueError('RPC 参数错误：' + (detail or 'RPC 不接受帮助参数')) from e


def interrupt(signum, frame):
    # A second cancellation cannot interrupt process-group cleanup.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise KeyboardInterrupt


def main():
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    rpc = len(sys.argv) > 1 and sys.argv[1] == 'rpc'
    emit = (lambda kind, data: print(json.dumps({'event': kind, 'data': data}, ensure_ascii=False), flush=True)) if rpc else emit_terminal
    try:
        if rpc:
            if len(sys.argv) != 2:
                raise ValueError('RPC 入口不接受命令行参数')
            r = rpc_arguments()
        elif len(sys.argv) > 1 and sys.argv[1] == '_rootfs':
            worker = argparse.ArgumentParser(prog='uuf _rootfs')
            worker.add_argument('--request', required=True)
            r = vars(worker.parse_args(sys.argv[2:]))
            r['operation'] = '_rootfs'
        else:
            r = vars(parser().parse_args())
        if not math.isfinite(r.get('timeout', 1)) or r.get('timeout', 1) <= 0:
            raise ValueError('时限必须大于零')
        confirm = (lambda phase, plan: confirm_rpc(emit, phase, plan)) if rpc else confirm_terminal
        dispatch(r, emit, confirm)
    except KeyboardInterrupt:
        emit('error', {'message': '任务中止，子进程已清理；若板端已写入，按日志检查，未自动回滚'})
        return 130
    except (OSError, ValueError, RuntimeError, TypeError, KeyError, UnicodeError,
            struct.error, tarfile.TarError, subprocess.TimeoutExpired) as e:
        emit('error', {'message': str(e)})
        return 1
    return 0
