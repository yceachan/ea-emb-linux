"""MBR owns geometry; component targets and boot descriptions own placement."""
from pathlib import Path, PurePosixPath
import json
import re
import secrets
import struct

BOARD = '100ask-imx6ull-pro'


def json_file(path):
    return json.loads(Path(path).read_text())


def target_path(value):
    if (not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_./-]+', value)
            or '..' in PurePosixPath(value).parts or str(PurePosixPath(value)) != value
            or value == '/' or len(value) > 200):
        raise ValueError(f'板端目标路径非法：{value}')
    return value


def targets(value):
    v = json_file(value) if isinstance(value, (str, Path)) else value
    if set(v) != {'board', 'kernel', 'dtb', 'rtfs'} or v['board'] != BOARD:
        raise ValueError('目标映射必须指定当前板卡和 kernel／dtb／rtfs')
    for name in ('kernel', 'dtb', 'rtfs'):
        p = v[name]
        if set(p) != ({'partition'} if name == 'rtfs' else {'partition', 'path'}):
            raise ValueError(f'{name} 目标映射字段错误')
        if type(p['partition']) is not int or not 1 <= p['partition'] <= 4:
            raise ValueError('目标必须明确选择 MBR 主分区编号 1–4')
        if name != 'rtfs':
            target_path(p['path'])
    if (v['kernel']['partition'] != v['dtb']['partition']
            or v['kernel']['partition'] == v['rtfs']['partition']
            or v['kernel']['path'] == v['dtb']['path']
            or '/extlinux/extlinux.conf' in (v['kernel']['path'], v['dtb']['path'])):
        raise ValueError('组件分区或文件目标冲突')
    return v


def firmware_target(value):
    v = json_file(value) if isinstance(value, (str, Path)) else value
    if (set(v) != {'area', 'offset', 'limit', 'boot_ack', 'boot_partition'}
            or v['area'] != 'boot0' or v['offset'] != 1024
            or type(v['limit']) is not int or not 0 < v['limit'] <= 0xffc00
            or v['limit'] % 512 or type(v['boot_ack']) is not int
            or v['boot_ack'] not in (0, 1) or v['boot_partition'] != 1):
        raise ValueError('固件部署描述必须为当前板卡 boot0 范围和启动设置')
    return v


def parse_mbr(data):
    if len(data) != 512:
        raise ValueError('MBR 输入必须恰好 512 字节')
    entries = []
    for n in range(1, 5):
        e = data[446 + (n - 1) * 16:462 + (n - 1) * 16]
        if e != bytes(16):
            start, sectors = struct.unpack_from('<II', e, 8)
            entries.append({'number': n, 'start': start, 'sectors': sectors,
                            'type': e[4], 'boot_flag': e[0]})
    return {'valid': data[510:] == b'\x55\xaa',
            'signature': f'{struct.unpack_from("<I", data, 440)[0]:08x}', 'entries': entries}


def geometry(data, mapping, capacity=None):
    mapping = targets(mapping)
    m = parse_mbr(data)
    wanted = {mapping['kernel']['partition'], mapping['rtfs']['partition']}
    if (not m['valid'] or int(m['signature'], 16) == 0
            or {p['number'] for p in m['entries']} != wanted):
        raise ValueError('MBR 必须明确对应 kernel 和 rtfs 两个主分区')
    parts = {p['number']: p for p in m['entries']}
    spans = []
    for p in parts.values():
        if (p['type'] != 0x83 or p['boot_flag'] not in (0, 0x80)
                or p['start'] < 8 or p['start'] % 8 or not p['sectors'] or p['sectors'] % 8
                or p['start'] + p['sectors'] > 0xffffffff
                or capacity is not None and p['start'] + p['sectors'] > capacity):
            raise ValueError('MBR 分区类型、对齐或容量非法')
        spans.append((p['start'], p['start'] + p['sectors']))
    spans.sort()
    if spans[0][1] > spans[1][0]:
        raise ValueError('MBR 分区重叠')
    if {p['number'] for p in parts.values() if p['boot_flag'] == 0x80} != {mapping['kernel']['partition']}:
        raise ValueError('只能将映射的 kernel 分区设为活动分区')
    return m, parts


def make_mbr(kernel_bytes, root_bytes, mapping, signature=None, capacity=None):
    signature = signature or secrets.token_hex(4)
    if not re.fullmatch('[0-9a-f]{8}', signature) or int(signature, 16) == 0:
        raise ValueError('MBR signature 必须为非零的 8 位小写十六进制')
    data = bytearray(512)
    struct.pack_into('<I', data, 440, int(signature, 16))
    start = 2048
    for name, size in (('kernel', kernel_bytes), ('rtfs', root_bytes)):
        if type(size) is not int or size < 32 * 1024 * 1024 or size % 4096:
            raise ValueError('分区容量必须不小于 32 MiB 且按 ext4 块对齐')
        n = mapping[name]['partition']
        off = 446 + (n - 1) * 16
        data[off:off + 8] = bytes([0x80 if name == 'kernel' else 0, 0xfe, 0xff, 0xff,
                                  0x83, 0xfe, 0xff, 0xff])
        struct.pack_into('<II', data, off + 8, start, size // 512)
        start += size // 512
    data[510:] = b'\x55\xaa'
    geometry(data, mapping, capacity)
    return bytes(data)


def parse_boot(text, label=None):
    entries, default, current = {}, None, None
    for raw in text.splitlines():
        fields = raw.split('#', 1)[0].split(None, 1)
        if not fields:
            continue
        key, value = fields[0].upper(), fields[1].strip() if len(fields) == 2 else ''
        if key == 'DEFAULT':
            default = value
        elif key == 'LABEL':
            if not value or value in entries:
                raise ValueError('extlinux LABEL 为空或重复')
            current = entries[value] = {}
        elif current is not None and key in ('LINUX', 'KERNEL', 'FDT', 'APPEND'):
            key = 'LINUX' if key == 'KERNEL' else key
            if key in current:
                raise ValueError('extlinux 所选启动字段重复')
            current[key] = value
    chosen = label or default
    if chosen is None and len(entries) == 1:
        chosen = next(iter(entries))
    if chosen not in entries:
        raise ValueError(f'需明确选择 extlinux label；候选：{list(entries)}')
    entry = entries[chosen]
    if not {'LINUX', 'FDT', 'APPEND'} <= entry.keys():
        raise ValueError('所选启动项缺少 LINUX、FDT 或 APPEND')
    return {'label': chosen, 'kernel': target_path(entry['LINUX']),
            'dtb': target_path(entry['FDT']), 'append': entry['APPEND']}


def boot_root(entry, signature, parts):
    roots = [x for x in entry['append'].split() if x.startswith('root=')]
    if len(roots) != 1:
        raise ValueError('所选启动项必须唯一引用 rtfs')
    match = re.fullmatch(r'root=PARTUUID=([0-9a-fA-F]{8})-([0-9a-fA-F]{2})', roots[0])
    if match is None or match[1].lower() != signature:
        raise ValueError('所选启动项的 root PARTUUID 与实际 MBR 不一致')
    number = int(match[2], 16)
    if number not in parts:
        raise ValueError('root PARTUUID 不对应实际分区')
    return number


def boot_text(description, mapping, data):
    if set(description) != {'label', 'kernel', 'dtb', 'append'}:
        raise ValueError('启动描述需要 label、kernel、dtb 和 append')
    if not re.fullmatch('[A-Za-z0-9_-]+', description['label']):
        raise ValueError('启动 LABEL 非法')
    if (description['kernel'] != mapping['kernel']['path']
            or description['dtb'] != mapping['dtb']['path']):
        raise ValueError('启动文件路径与组件映射不一致')
    append = description['append']
    if not isinstance(append, str) or any(ord(c) < 32 or ord(c) == 127 for c in append) or '${' in append:
        raise ValueError('APPEND 必须为明确的单行参数')
    m, parts = geometry(data, mapping)
    roots = [x for x in append.split() if x.startswith('root=')]
    expected = f"root=PARTUUID={m['signature']}-{mapping['rtfs']['partition']:02x}"
    if roots and roots != [expected]:
        raise ValueError('启动描述必须引用 MBR 中映射的 rtfs')
    if not roots:
        append += ' ' + expected
        if 'rootwait' not in append.split():
            append += ' rootwait'
        if not {'ro', 'rw'} & set(append.split()):
            append += ' rw'
    text = (f"DEFAULT {description['label']}\nTIMEOUT 0\nLABEL {description['label']}\n"
            f"  LINUX {description['kernel']}\n  FDT {description['dtb']}\n  APPEND {append.strip()}\n")
    boot_root(parse_boot(text), m['signature'], parts)
    return text
