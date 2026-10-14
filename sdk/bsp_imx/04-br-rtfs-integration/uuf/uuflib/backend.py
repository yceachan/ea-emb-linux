"""One operation backend for the CLI and the later GUI."""
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import time

from . import transport
from .images import BLOCK, WINDOW, Sparse, sha256
from .model import (BOARD, firmware_target, targets, parse_mbr, geometry,
                    parse_boot, boot_root)
from .package import ROOT, validate_firmware, component, validate_sparse, superblock, unpack

INFO = ('abi', 'cid', 'user', 'boot', 'erase', 'erased', 'partconf')
SAVE_WINDOW = 64 * 1024 * 1024


class Session:
    def __init__(self, request, emit, confirm):
        self.request, self.emit, self.confirm = request, emit, confirm
        self.uuu = shutil.which(request.get('uuu') or os.environ.get('UUF_UUU', 'uuu'))
        if not self.uuu:
            raise ValueError('需要 UUU；指定 --uuu 或 UUF_UUU')
        base = Path(os.environ.get('UUF_LOG_ROOT', str(Path.home() / 'uuf-logs')))
        name = datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + secrets.token_hex(4)
        self.work = Path(request['log_dir']).resolve() if request.get('log_dir') else base / name
        self.work.mkdir(parents=True, exist_ok=False)
        self.emit('workspace', {'path': str(self.work)})
        self.mapping = targets(request['targets']) if request.get('targets') else None
        self.fw = firmware_target(request.get('firmware_target') or ROOT / 'firmware/target.json')
        self.files, self.images = {}, {}
        self.mbr = None
        self.bundle = None
        self.actual = None
        self.usb = None
        self.sequence = 0
        self.deadline = None

    def stage(self, source, name, expected=None):
        source = Path(source).resolve()
        original = sha256(source)
        if expected is not None and original != expected:
            raise ValueError(f'归档输入在校验后变化：{source}')
        dest = self.work / name
        shutil.copyfile(source, dest)
        if sha256(dest) != original:
            raise ValueError(f'暂存期间输入变化：{source}')
        self.files[name] = {'source': str(source), 'path': str(dest),
                            'source_bytes': dest.stat().st_size, 'sha256': original}
        return dest

    def check_staged(self):
        for name, value in self.files.items():
            if sha256(value['path']) != value['sha256']:
                raise ValueError(f'暂存输入在确认期间变化：{name}')

    def script(self, lines, name=None):
        self.sequence += 1
        path = self.work / (name or f'{self.sequence:03d}.uuu')
        timeout = int(self.request.get('timeout', 3600) * 1000)
        bounded = [line.replace('FB:', f'FB[-t {timeout}]:', 1)
                   if line.startswith(('FB: ucmd ', 'FB: flash ')) else line for line in lines]
        path.write_text('uuu_version 1.2.39\n' + '\n'.join(bounded) + '\nFB: Done\n')
        return path

    def call(self, lines, *, dry=False, name=None):
        script = self.script(lines, name)
        remaining = self.request.get('timeout', 3600)
        if self.deadline is not None:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('任务超过总时限')
        options = ['-dry', script.name] if dry else ['-v', '-m', self.usb, '-t', '30', '-T', '60', script.name]
        return transport.run(self.uuu, options, self.work, script.with_suffix('.log'),
                             30 if dry else remaining, self.emit, script=script, dry=dry)

    def get(self, commands, keys):
        text = self.call(commands + [f'FB: getvar uuf-{k}' for k in keys])
        values = transport.getvars(text, self.usb)
        if any('uuf-' + k not in values for k in keys):
            raise ValueError('loader 响应缺少请求的信息字段')
        return {k: values['uuf-' + k] for k in keys}

    def exported(self, operation):
        size = int(self.get(['FB: ucmd uuf ' + operation], ['size'])['size'], 16)
        if not 0 < size <= 8192:
            raise ValueError('板端导出长度非法')
        keys = [f'data{i}' for i in range(math.ceil(size / 24))]
        values = self.get([], keys)
        data = bytes.fromhex(''.join(values[k] for k in keys))
        if len(data) != size:
            raise ValueError('板端导出数据截断')
        return data

    def info(self):
        v = self.get(['FB: ucmd uuf info'], INFO)
        if v['abi'] != '1' or not re.fullmatch('[0-9a-f]{32}', v['cid']) or int(v['cid'], 16) == 0:
            raise ValueError('loader ABI 或 eMMC CID 非法')
        result = {'board': BOARD, 'mmc': 1, 'cid': v['cid'], 'boot_sectors': int(v['boot'], 16),
                  **{k: int(v[k], 16) for k in INFO if k not in ('abi', 'cid', 'boot')}}
        if not 0 < result['user'] <= 0xffffffff or result['boot_sectors'] <= 0 or result['erase'] <= 0:
            raise ValueError('实际设备容量或擦除粒度非法')
        return result

    def probe(self, with_boot=False):
        actual = self.info()
        data = self.exported('export 0 0 200')
        table = parse_mbr(data)
        actual.update(mbr_hex=data.hex(), mbr_sha256=hashlib.sha256(data).hexdigest(),
                      mbr_valid=table['valid'], mbr_entries=table['entries'])
        if with_boot:
            selected = self.request.get('kernel_part', 0)
            kp = int(self.get([f'FB: ucmd uuf locate {selected:x}'], ['kernel-part'])['kernel-part'], 16)
            conf = self.exported(f'exportfile {kp:x} /extlinux/extlinux.conf').decode('utf-8')
            entry = parse_boot(conf, self.request.get('label'))
            parts = {p['number']: p for p in table['entries']}
            rp = boot_root(entry, table['signature'], parts)
            derived = targets({'board': BOARD, 'kernel': {'partition': kp, 'path': entry['kernel']},
                               'dtb': {'partition': kp, 'path': entry['dtb']}, 'rtfs': {'partition': rp}})
            _, parts = geometry(data, derived, actual['user'])
            if self.mapping is not None and self.mapping != derived:
                raise ValueError('组件角色或目标路径与实际 extlinux／root PARTUUID 不一致')
            actual.update(targets=derived, boot=entry, boot_text=conf)
            p = parts[kp]
            sb = self.exported(f"export 0 {p['start'] + 2:x} 400")
            actual['kernel_fs'] = superblock(sb, p['sectors'] * 512,
                                            bool(self.request.get('kernel') or self.request.get('dtb')))
            for kind in ('kernel', 'dtb'):
                if self.request.get(kind):
                    self.get([f"FB: ucmd uuf writable {kp:x} {derived[kind]['path']}"], [])
        return actual

    def preflight(self):
        r = self.request
        firmware = r.get('firmware')
        if r['operation'] == 'deploy':
            self.bundle = unpack(r['archive'], self.work / 'bundle')
            folder = self.bundle['folder']
            manifest = self.bundle['manifest']
            self.mapping = manifest['targets']
            self.fw = manifest['firmware_target']
            paths = self.bundle['paths']
            firmware = paths['uboot'].parent
            r['uboot'] = True
            r['rtfs'] = str(paths['rtfs_sparse'])
            self.mbr = self.bundle['mbr']
            sums = self.bundle['sums']
            for kind, name in (('kernel', 'kernel.bin'), ('dtb', 'board.dtb'),
                               ('boot_config', 'extlinux.conf'), ('mbr', 'mbr.bin'),
                               ('kernel_sparse', 'kernel.sparse'), ('rtfs_sparse', 'rtfs.sparse')):
                p = paths[kind]
                self.stage(p, name, sums[p.relative_to(folder).as_posix()])
            self.images = {'kernel': self.work / 'kernel.sparse', 'rtfs': self.work / 'rtfs.sparse'}
            for name in ('kernel', 'rtfs'):
                self.files[name + '.sparse'].update(sparse=self.bundle['images'][name]['sparse'],
                                                   filesystem=self.bundle['images'][name]['fs'])
        if firmware is None:
            raise ValueError('需要 M1 firmware 发布目录，或完整部署归档')
        expected = (self.bundle['sums'][self.bundle['manifest']['files']['uboot']]
                    if self.bundle is not None else validate_firmware(firmware)['u-boot-dtb.imx'])
        self.stage(Path(firmware) / 'u-boot-dtb.imx', 'loader.imx', expected)
        if self.files['loader.imx']['source_bytes'] > self.fw['limit']:
            raise ValueError('固件镜像超过部署描述范围')
        for kind, name in (('kernel', 'kernel.bin'), ('dtb', 'board.dtb')):
            if r.get(kind):
                component(kind, self.stage(r[kind], name))
        if r['operation'] == 'update' and r.get('rtfs'):
            self.images['rtfs'] = self.stage(r['rtfs'], 'rtfs.sparse')
        needs_mapping = bool(self.images or r.get('kernel') or r.get('dtb')
                             or r['operation'] == 'erase' and r['region'] != 'firmware')
        if needs_mapping and self.mapping is None:
            raise ValueError('独立组件操作需要明确的 --targets 描述')
        if r.get('expected_mbr'):
            self.mbr = self.stage(r['expected_mbr'], 'expected-mbr.bin').read_bytes()
            if needs_mapping:
                geometry(self.mbr, self.mapping)
            else:
                parse_mbr(self.mbr)
        if r['operation'] == 'update' and not any(r.get(k) for k in ('uboot', 'kernel', 'dtb', 'rtfs')):
            raise ValueError('至少选择一个更新组件')
        self.validate_images(self.mbr)
        draft = self.plan()
        self.emit('plan', draft)
        lines = self.boot_lines() + self.write_lines(draft, protect=False)
        self.call(lines, dry=True, name='host-preflight.uuu')
        (self.work / 'plan.json').write_text(json.dumps(draft, ensure_ascii=False, indent=2) + '\n')
        return draft

    def validate_images(self, data=None):
        parts = geometry(data, self.mapping)[1] if data is not None and self.images else None
        for name, path in self.images.items():
            record = self.files[name + '.sparse']
            if 'sparse' not in record:
                sp = Sparse(path)
                with tempfile.TemporaryDirectory(prefix='image-check-', dir=self.work) as temp:
                    _, _, info = validate_sparse(path, temp, sp.blocks * BLOCK, writable=name == 'kernel')
                record.update(sparse=sp.summary(), filesystem=info)
            if parts is not None and record['sparse']['logical_bytes'] != parts[self.mapping[name]['partition']]['sectors'] * 512:
                raise ValueError('Sparse 逻辑长度与 MBR 目标分区容量不同')

    def plan(self, actual=None):
        r = self.request
        parts = None
        if actual is not None:
            if self.fw['offset'] + self.fw['limit'] > actual['boot_sectors'] * 512:
                raise ValueError('固件部署范围超过真实 boot0')
            data = bytes.fromhex(actual['mbr_hex'])
            if r.get('expected_mbr') and data != self.mbr:
                raise ValueError('实际 MBR 与独立操作的预期快照不同')
            if r['operation'] == 'deploy':
                _, parts = geometry(self.mbr, self.mapping, actual['user'])
            elif self.images or r.get('kernel') or r.get('dtb') or r['operation'] == 'erase' and r['region'] != 'firmware':
                if actual.get('targets') != self.mapping:
                    raise ValueError('独立操作的目标角色尚未与实际启动路径核对')
                _, parts = geometry(data, self.mapping, actual['user'])
            if self.images:
                self.validate_images(self.mbr if r['operation'] == 'deploy' else data)
            if r.get('kernel') or r.get('dtb'):
                required = sum(self.files[name + '.bin' if name == 'kernel' else 'board.dtb']['source_bytes']
                               for name in ('kernel', 'dtb') if r.get(name))
                if actual['kernel_fs']['free_bytes'] < required:
                    raise ValueError('实际 kernel ext4 空闲空间不足以安全覆盖选中原始文件')
        elif self.mbr is not None and self.mapping is not None:
            _, parts = geometry(self.mbr, self.mapping)
        writes = []
        pending = [] if actual is not None else ['CID、真实 user area／boot0 容量与板载 MBR 待 loader 启动后复核']
        if r['operation'] == 'erase':
            if r['region'] == 'firmware':
                offset, size = r.get('offset'), r.get('bytes')
                if (type(offset) is not int or type(size) is not int or offset < 0 or size <= 0
                        or offset % 512 or size % 512):
                    raise ValueError('固件擦除须明确提供按扇区对齐的 offset 和 bytes')
                if actual is not None and offset + size > actual['boot_sectors'] * 512:
                    raise ValueError('明确擦除范围超过真实 boot0')
                writes.append({'kind': 'erase', 'region': 'firmware', 'hw': 1,
                               'start_sector': offset // 512, 'write_bytes': size})
            else:
                n = self.mapping[r['region']]['partition']
                if parts is not None:
                    p = parts[n]
                    writes.append({'kind': 'erase', 'region': r['region'], 'hw': 0, 'partition': n,
                                   'start_sector': p['start'], 'partition_bytes': p['sectors'] * 512,
                                   'write_bytes': p['sectors'] * 512})
                else:
                    pending.append('擦除范围待实际 MBR 与启动角色核对')
            if actual is None:
                pending.append('擦除粒度待真实设备核对')
            else:
                for w in writes:
                    grain = actual['erase'] * 512
                    if w['start_sector'] * 512 % grain or w['write_bytes'] % grain:
                        raise ValueError('目标不满足真实擦除粒度；拒绝扩大范围')
        else:
            if r.get('uboot'):
                v = self.files['loader.imx']
                writes.append({'kind': 'uboot', 'hw': 1, 'start_sector': self.fw['offset'] // 512,
                               'source_bytes': v['source_bytes'], 'write_bytes': v['source_bytes'],
                               'sha256': v['sha256'], 'conditional': '目标 hash 相同则免写'})
            if r['operation'] == 'deploy':
                writes.append({'kind': 'mbr', 'hw': 0, 'start_sector': 0, 'write_bytes': 512,
                               'sha256': hashlib.sha256(self.mbr).hexdigest()})
            for name in ('kernel', 'rtfs'):
                if name in self.images:
                    n = self.mapping[name]['partition']
                    sp = self.files[name + '.sparse']['sparse']
                    item = {'kind': name + '-partition', 'hw': 0, 'partition': n,
                            'source_bytes': sp['container_bytes'], 'logical_bytes': sp['logical_bytes'],
                            'write_bytes': sp['written_bytes'], 'sha256': self.files[name + '.sparse']['sha256']}
                    if parts is not None:
                        item.update(start_sector=parts[n]['start'], partition_bytes=parts[n]['sectors'] * 512)
                    else:
                        pending.append(f'{name} 分区容量与起点待实际 MBR 核对')
                    writes.append(item)
            for name, source in (('kernel', 'kernel.bin'), ('dtb', 'board.dtb')):
                if r.get(name):
                    v = self.files[source]
                    writes.append({'kind': name, 'hw': 0, 'partition': self.mapping[name]['partition'],
                                   'target_path': self.mapping[name]['path'],
                                   'source_bytes': v['source_bytes'], 'write_bytes': v['source_bytes'],
                                   'sha256': v['sha256']})
        return {'operation': r['operation'], 'board': BOARD, 'actual': actual,
                'targets': self.mapping, 'firmware_target': self.fw, 'writes': writes,
                'inputs': self.files, 'pending_device_checks': pending,
                'logs': str(self.work), 'cold_boot': 'pending-developer-validation'}

    def boot_lines(self):
        return ['SDP: dcd -f loader.imx', 'SDP: write -f loader.imx -ivt 0', 'SDP: jump -f loader.imx -ivt 0']

    def write_lines(self, plan, protect=True):
        lines, slots = [], 0
        actual = plan['actual']
        def cmd(text):
            lines.append('FB: ucmd ' + text)
        def save(hw, start, size):
            nonlocal slots
            for offset in range(0, size, SAVE_WINDOW):
                if slots >= 2048:
                    raise ValueError('未选内容保护超过板端快照槽位')
                length = min(SAVE_WINDOW, size - offset)
                cmd(f'uuf save {slots:x} {hw:x} {start + offset // 512:x} {length:x}')
                slots += 1
        if actual is not None and protect:
            cmd(f"uuf matchcid {actual['cid']}")
            cmd(f"uuf verify 0 0 200 {actual['mbr_sha256']}")
            if actual.get('boot_text') is not None:
                conf = actual['boot_text'].encode('utf-8')
                cmd(f"uuf file {actual['targets']['kernel']['partition']:x} /extlinux/extlinux.conf "
                    f"{len(conf):x} {hashlib.sha256(conf).hexdigest()}")
            firmware_writes = [w for w in plan['writes'] if w['hw'] == 1]
            if not firmware_writes:
                save(1, 0, actual['boot_sectors'] * 512)
            else:
                w = firmware_writes[0]
                save(1, 0, w['start_sector'] * 512)
                end = w['start_sector'] + math.ceil(w['write_bytes'] / 512)
                if end < actual['boot_sectors']:
                    save(1, end, (actual['boot_sectors'] - end) * 512)
            if plan['operation'] != 'deploy' and actual.get('targets') is not None:
                _, parts = geometry(bytes.fromhex(actual['mbr_hex']), self.mapping)
                chosen_parts = {w['partition'] for w in plan['writes'] if 'partition' in w}
                for n, p in parts.items():
                    if n not in chosen_parts:
                        save(0, p['start'], p['sectors'] * 512)
            for w in plan['writes']:
                if w['kind'].endswith('-partition'):
                    name = w['kind'].removesuffix('-partition')
                    for chunk in Sparse(self.images[name]).chunks:
                        if chunk.kind == 0xcac3:
                            save(0, w['start_sector'] + chunk.start * 8, chunk.blocks * BLOCK)
            if self.request.get('kernel') or self.request.get('dtb'):
                paths = ['/extlinux/extlinux.conf'] + [self.mapping[k]['path'] for k in ('kernel', 'dtb')
                                                       if not self.request.get(k)]
                for path in paths:
                    if slots >= 2048:
                        raise ValueError('文件保护超过板端快照槽位')
                    cmd(f"uuf filesave {slots:x} {self.mapping['kernel']['partition']:x} {path}")
                    slots += 1
        for w in plan['writes']:
            kind = w['kind']
            if kind == 'uboot':
                lines.append('FB: download -f loader.imx')
                cmd(f"uuf fw 1 {w['start_sector']:x} {w['write_bytes']:x} {w['sha256']}")
                lines.append('FB: getvar uuf-fw-result')
            elif kind == 'mbr':
                lines.append('FB: download -f mbr.bin')
                cmd('mmc dev 1 0')
                cmd('mmc write 0x82000000 0 1')
                cmd(f"uuf verify 0 0 200 {w['sha256']}")
            elif kind.endswith('-partition'):
                if 'start_sector' not in w:
                    continue  # offline plan explicitly marks device geometry pending
                name = kind.removesuffix('-partition')
                cmd(f"setenv fastboot_raw_partition_uuf_part {w['start_sector']:x} {w['partition_bytes'] // 512:x} mmcpart 0")
                lines.append(f'FB: flash uuf_part {name}.sparse')
                for start, count, digest in Sparse(self.images[name]).checks(w['start_sector']):
                    cmd(f'uuf verify 0 {start:x} {count * 512:x} {digest}')
            elif kind in ('kernel', 'dtb'):
                name = 'kernel.bin' if kind == 'kernel' else 'board.dtb'
                lines.append('FB: download -f ' + name)
                cmd(f"uuf writefile {w['partition']:x} {w['target_path']} {w['write_bytes']:x} {w['sha256']}")
            elif kind == 'erase':
                cmd(f"uuf erase {w['hw']:x} {w['start_sector']:x} {w['write_bytes']:x}")
        if self.request.get('uboot'):
            cmd(f"uuf bootconf {self.fw['boot_ack']:x} {self.fw['boot_partition']:x}")
        for slot in range(slots):
            cmd(f'uuf keep {slot:x}')
        if actual is not None and plan['operation'] != 'deploy':
            cmd(f"uuf verify 0 0 200 {actual['mbr_sha256']}")
        return lines

    def execute(self):
        draft = self.preflight()
        if self.request.get('dry_run'):
            self.emit('result', {'state': 'dry-run-passed', 'plan': draft, 'hardware_access': False})
            return draft
        self.confirm('host-plan', draft)
        self.deadline = time.monotonic() + self.request.get('timeout', 3600)
        self.check_staged()
        listed = transport.run(self.uuu, ['-lsusb'], self.work, self.work / 'usb.log', 30, self.emit)
        self.usb = transport.select_rom(listed, self.request.get('usb_path'))
        self.call(self.boot_lines(), name='loader.uuu')
        needs_boot = (self.request['operation'] == 'update' and bool(self.images or self.request.get('kernel') or self.request.get('dtb'))
                      or self.request['operation'] == 'erase' and self.request['region'] != 'firmware'
                      or self.request.get('with_boot', False))
        actual = self.probe(needs_boot)
        self.actual = actual
        (self.work / 'target.json').write_text(json.dumps(actual, ensure_ascii=False, indent=2) + '\n')
        self.emit('target', actual)
        if self.request['operation'] == 'inspect':
            self.emit('result', {'state': 'inspected', 'target': actual})
            return actual
        plan = self.plan(actual)
        self.emit('plan', plan)
        (self.work / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
        lines = self.write_lines(plan)
        self.call(lines, dry=True, name='target-preflight.uuu')
        self.confirm('target-write', plan)
        if self.probe(needs_boot) != actual:
            raise ValueError('确认期间 CID、设备信息、MBR 或启动描述变化；重新开始')
        self.check_staged()
        text = self.call(lines, name='write-verify.uuu')
        after = self.info()
        expected = ((self.fw['boot_ack'] << 6) | (self.fw['boot_partition'] << 3)
                    if self.request.get('uboot') else actual['partconf'])
        if after['cid'] != actual['cid'] or after['partconf'] != expected:
            raise ValueError('写后 CID 或 EXT_CSD 启动设置不一致')
        if self.request['operation'] == 'deploy':
            final = self.probe(False)
            if bytes.fromhex(final['mbr_hex']) != self.mbr:
                raise ValueError('写后 MBR 与归档不同')
            kp = self.mapping['kernel']['partition']
            conf = self.exported(f'exportfile {kp:x} /extlinux/extlinux.conf')
            if hashlib.sha256(conf).hexdigest() != self.files['extlinux.conf']['sha256']:
                raise ValueError('写后启动文件与归档不同')
            self.emit('target', final)
        fw_result = transport.getvars(text, self.usb).get('uuf-fw-result')
        if self.request.get('uboot') and fw_result not in ('written', 'skipped'):
            raise ValueError('缺少固件写入／免写结果')
        result = {'state': 'written-and-verified', 'plan': plan, 'logs': str(self.work),
                  'firmware': fw_result, 'cold_boot': 'pending-developer-validation'}
        (self.work / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        self.emit('result', result)
        return result
