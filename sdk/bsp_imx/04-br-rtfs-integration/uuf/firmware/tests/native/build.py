"""Compile the configured fixed U-Boot ext4 sources; no complete SDK build."""
from pathlib import Path
import shutil
import subprocess
import sys
src, output = map(Path, sys.argv[1:])
local = Path(__file__).resolve().parent
shim = output / 'shim'
shim.mkdir(parents=True, exist_ok=True)
headers = ['blk.h','compiler.h','fs.h','div64.h','malloc.h','part.h','rtc.h','u-boot/uuid.h',
           'config.h','fs_internal.h','log.h','memalign.h','linux/stat.h','linux/time.h',
           'asm/byteorder.h','asm/cache.h','linux/compat.h','linux/crc16.h']
for name in headers:
    p = shim / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text('#include "' + str(local / 'uuf_host.h') + '"\n')
for name in ('ext4fs.h','ext_common.h'):
    shutil.copyfile(src / 'include' / name, shim / name)
write_source = src / 'fs/ext4/ext4_write.c'
write_text = write_source.read_text()
deinit = 'int ext4fs_deinit(void)\n{'
if write_text.count(deinit) != 1:
    raise SystemExit('configured ext4_write.c does not expose the patched ext4fs_deinit')
hook = '''int ext4fs_deinit(void)
{
#ifdef UUF_NATIVE_TEST
    extern void uuf_native_deinit_begin(void);
    uuf_native_deinit_begin();
#endif'''
test_write = output / 'ext4_write_test.c'
write_text = write_text.replace(deinit, hook, 1)
jsb_read = 'else if (!ext4fs_devread((lbaint_t)blknr * fs->sect_perblk,'
if write_text.count(jsb_read) != 1:
    raise SystemExit('cannot locate the journal superblock data read')
write_text = write_text.replace(jsb_read,
    'else if ((uuf_native_jsb_read_begin(), !ext4fs_devread((lbaint_t)blknr * fs->sect_perblk,', 1)
jsb_tail = '0, fs->blksz, temp_buff) || ext4fs_io_error) {'
if write_text.count(jsb_tail) != 1:
    raise SystemExit('cannot locate the journal superblock read completion')
write_text = write_text.replace(jsb_tail, '0, fs->blksz, temp_buff)) || ext4fs_io_error) {', 1)
test_write.write_text(write_text)
files = [src / 'fs/ext4' / name for name in ('ext4fs.c','ext4_common.c','dev.c')]
files += [test_write, src / 'fs/ext4/ext4_journal.c', src / 'fs/fs_internal.c']
subprocess.run(['cc','-g','-O1','-ffunction-sections','-fdata-sections','-I'+str(shim),'-I'+str(local),
                '-I'+str(src/'fs/ext4'),
                '-DUUF_NATIVE_TEST','-include',str(local/'uuf_host.h'),*map(str,files),str(local/'harness.c'),
                '-Wl,--gc-sections','-o',str(output/'ext4-test')],check=True)
