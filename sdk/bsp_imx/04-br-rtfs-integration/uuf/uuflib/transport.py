"""UUU 1.5.21 execution, strict per-command completion, bounded PTY output."""
import errno
import os
from pathlib import Path
import pty
import re
import selectors
import subprocess
import time

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def plain(data):
    return ANSI.sub('', data.decode('utf-8', errors='replace'))


def steps(text):
    return re.findall(r'Start Cmd:([^\r\n]+)(.*?)(?=Start Cmd:|\Z)', text, re.S)


def complete(text, script, dry=False):
    expected = [x.strip() for x in Path(script).read_text().splitlines()
                if re.match(r'^(SDP|FB)(?:\[-t [0-9]+\])?:', x)]
    if dry:
        actual = [x.strip() for x in text.splitlines() if re.match(r'^(SDP|FB)(?:\[-t [0-9]+\])?:', x)]
        return all([x for x in actual if x.startswith(p)] == [x for x in expected if x.startswith(p)]
                   for p in ('SDP', 'FB'))
    records = steps(text)
    return ([cmd.strip() for cmd, _ in records] == expected
            and all(re.search(r'>Okay \(', body) for _, body in records))


from .process import stop

def run(uuu, options, work, logfile, timeout, emit, *, script=None, dry=False):
    master, slave = pty.openpty()
    process = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen([str(uuu), *map(str, options)], cwd=work,
                                   stdin=subprocess.DEVNULL, stdout=slave, stderr=slave,
                                   start_new_session=True)
        os.close(slave)
        slave = None
        with Path(logfile).open('wb') as log, selectors.DefaultSelector() as poller:
            poller.register(master, selectors.EVENT_READ)
            eof = False
            while not eof:
                if time.monotonic() > deadline:
                    raise RuntimeError(f'UUU 超时；查看 {logfile}')
                for _, _ in poller.select(timeout=0.1):
                    try:
                        data = os.read(master, 65536)
                    except OSError as error:
                        if error.errno != errno.EIO:
                            raise
                        data = b''
                    if not data:
                        eof = True
                        break
                    log.write(data)
                    log.flush()
                    emit('log', {'text': plain(data)})
            status = process.wait(timeout=max(.1, deadline - time.monotonic()))
        text = plain(Path(logfile).read_bytes())
        echoes = {line.strip() for line in Path(script).read_text().splitlines()} if script is not None else set()
        diagnostics = '\n'.join(line for line in text.splitlines()
                                if line.strip().removeprefix('Start Cmd:').strip() not in echoes)
        if status or re.search(r'\b(?:Error|Fail|Failed)\b', diagnostics, re.I):
            raise RuntimeError(f'UUU 失败（退出码 {status}）；查看 {logfile}')
        if script is not None and not complete(text, script, dry):
            raise RuntimeError(f'UUU 缺少完整命令或成功记录；查看 {logfile}')
        return text
    finally:
        if process is not None:
            stop(process)
        if slave is not None:
            os.close(slave)
        os.close(master)


def rom_devices(text):
    found = []
    for line in text.splitlines():
        f = line.split()
        if len(f) >= 5 and f[1:3] == ['MX6ULL', 'SDP:'] and [x.lower() for x in f[3:5]] == ['0x15a2', '0x0080']:
            if not re.fullmatch(r'[0-9]+:[0-9]+(?:\.[0-9]+)*', f[0]):
                raise ValueError('UUU 返回非法 USB 路径')
            found.append(f[0])
    return found


def select_rom(text, requested):
    found = rom_devices(text)
    if requested:
        if found.count(requested) != 1:
            raise ValueError('指定 ROM USB 路径不存在或重复')
        return requested
    if len(found) != 1:
        raise ValueError(f'发现 {len(found)} 块 ROM 设备；明确选择 --usb-path')
    return found[0]


def getvars(text, usbpath):
    values = {}
    for cmd, body in steps(text):
        cmd = cmd.strip()
        if not cmd.startswith('FB: getvar '):
            continue
        prefix, sep, _ = body.partition(usbpath + '>Okay (')
        value = prefix.strip()
        if not sep or not re.fullmatch('[A-Za-z0-9_-]+', value):
            raise ValueError(f'无法解析 UUU getvar 响应：{cmd}')
        key = cmd.removeprefix('FB: getvar ')
        if key in values:
            raise ValueError('UUU getvar 重复响应')
        values[key] = value.lower()
    return values
