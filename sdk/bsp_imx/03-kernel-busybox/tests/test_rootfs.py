"""Host-only rootfs assembly and archive checks."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

BSP = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('rootfs_package', BSP / 'rootfs/package.py')
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class ArchiveTests(unittest.TestCase):
    def test_package_assembly_includes_boot_and_busybox(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            work, kernel = base / 'work', base / 'kernel'
            (work / 'out').mkdir(parents=True)
            (work / 'install/bin').mkdir(parents=True)
            (work / 'out/busybox').write_bytes(b'host-test fixture, not an ARM artifact')
            (work / 'install/bin/busybox').write_bytes((work / 'out/busybox').read_bytes())
            (work / 'install/bin/busybox').chmod(0o755)
            # All configured applets are symlinks in this synthetic install tree.
            applets = [line.split('=')[0][7:].lower() for line in
                       (BSP / 'rootfs/board.config').read_text().splitlines()
                       if line.startswith('CONFIG_') and line.endswith('=y')]
            applets += ['sh', 'init', 'poweroff']
            applets = sorted(set(applets) - {'busybox'})
            for name in applets:
                (work / 'install/bin' / name).symlink_to('busybox')
            # init lives in /sbin on the real install tree.
            (work / 'install/sbin').mkdir()
            (work / 'install/sbin/init').symlink_to('../bin/busybox')
            (work / 'out/busybox.links').write_text(''.join(f'/bin/{name}\n' for name in applets))
            (work / 'out/source-revision').write_bytes((BSP / 'rootfs/base-revision').read_bytes())
            (work / 'out/.config').write_bytes((BSP / 'rootfs/board.config').read_bytes())
            (work / 'out/bsp-inputs.sha256').write_text(''.join(
                f'{package.digest(p)}  {p.relative_to(BSP)}\n'
                for folder in ['rootfs'] for p in sorted((BSP / folder).rglob('*'))
                if p.is_file() and '__pycache__' not in p.parts))
            (work / 'out/SHA256SUMS').write_text(''.join(
                f'{package.digest(work / "out" / name)}  {name}\n'
                for name in ['busybox', '.config', 'busybox.links', 'source-revision', 'bsp-inputs.sha256']))
            (kernel / 'arch/arm/boot/dts/nxp/imx').mkdir(parents=True)
            (kernel / 'arch/arm/boot/zImage').write_bytes(b'test kernel')
            (kernel / 'arch/arm/boot/dts/nxp/imx/imx6ull-100ask-pro.dtb').write_bytes(b'test dtb')
            (kernel / 'source-revision').write_text('test-kernel-source\n')
            (kernel / 'SHA256SUMS').write_text(''.join(
                f'{package.digest(p)}  {p.relative_to(kernel)}\n'
                for p in sorted(kernel.rglob('*')) if p.is_file()))
            result = subprocess.run(['python3', str(BSP / 'rootfs/package.py'), str(work),
                                     str(kernel), str(base / 'package')], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output = base / 'package'
            self.assertTrue((output / 'rootfs/boot/extlinux/extlinux.conf').is_file())
            self.assertFalse((output / 'rescue').exists())
            self.assertFalse((output / 'rescue.cpio.gz').exists())
            with tarfile.open(output / 'rootfs.tar.gz') as archive:
                self.assertTrue(all(item.uid == item.gid == 0 for item in archive))

    def test_tar_metadata_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'tree'
            (root / 'dev').mkdir(parents=True)
            (root / 'bin').mkdir()
            (root / 'tmp').mkdir(mode=0o1777)
            (root / 'tmp').chmod(0o1777)
            (root / 'bin/busybox').write_bytes(b'test binary')
            (root / 'bin/busybox').chmod(0o755)
            (root / 'bin/sh').symlink_to('busybox')
            package.write_tar(root, base / 'rootfs.tar.gz')
            with tarfile.open(base / 'rootfs.tar.gz') as archive:
                self.assertTrue(all(item.uid == item.gid == 0 for item in archive))
                self.assertEqual(archive.getmember('tmp').mode, 0o1777)
                self.assertEqual(archive.getmember('bin/sh').linkname, 'busybox')


if __name__ == '__main__':
    unittest.main()
