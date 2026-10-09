"""Bind download packages to the migrated, fixed 04 firmware inputs."""
import json
from pathlib import Path
import shutil

from images import sha256, validate_imx

BUILD_REQUIRED = {"u-boot-dtb.imx", ".config", "source-revision", "bsp-inputs.sha256", "image-info.txt"}
BOOT_REQUIRED = {"loader.imx", "product.imx", "uboot.config", "uboot-inputs.sha256",
                 "source-revision", "image-info.txt", "firmware.json"}

OPTIONS = {
    "CONFIG_ENV_IS_NOWHERE": "y", "CONFIG_BOARD_LATE_INIT": "y",
    "CONFIG_CMD_SYSBOOT": "y", "CONFIG_CMD_FAT": "y", "CONFIG_FAT_WRITE": "y",
    "CONFIG_SHA256": "y", "CONFIG_FASTBOOT_UUU_SUPPORT": "y",
    "CONFIG_FASTBOOT_FLASH_MMC_DEV": "1", "CONFIG_FASTBOOT_BUF_ADDR": "0x82000000",
    "CONFIG_FASTBOOT_BUF_SIZE": "0x1000000", "CONFIG_FASTBOOT_MMC_USER_SUPPORT": "y",
    "CONFIG_FASTBOOT_MMC_USER_NAME": '"all"',
    "CONFIG_BOOTCOMMAND": '"mmc dev 1 0 && sysboot mmc 1:1 fat 0x84000000 /extlinux/extlinux.conf"',
}


def inputs(bsp):
    root = Path(bsp)
    names = ["base-revision", "register-board.patch", "build.sh"]
    names += sorted(str(p.relative_to(root)) for p in (root / "overlay").rglob("*") if p.is_file())
    return "".join(f"{sha256(root / name)}  {name}\n" for name in names)


def stage_build(source, folder, bsp, sums):
    """Normalize only verified firmware build records, with no rootfs dependency."""
    for name, target in (("u-boot-dtb.imx", "loader.imx"), ("u-boot-dtb.imx", "product.imx"),
                         (".config", "uboot.config"), ("bsp-inputs.sha256", "uboot-inputs.sha256"),
                         ("source-revision", "source-revision"), ("image-info.txt", "image-info.txt")):
        shutil.copyfile(source / name, folder / target)
        if sha256(folder / target) != sums[name]:
            raise ValueError(f"制作固件快照期间输入改变：{name}")
    identity = {"policy": 1, "revision": (folder / "source-revision").read_text().strip(),
                "inputs_sha256": sha256(folder / "uboot-inputs.sha256"),
                "config_sha256": sha256(folder / "uboot.config"),
                "image_sha256": sha256(folder / "loader.imx")}
    (folder / "firmware.json").write_text(json.dumps(identity, indent=2) + "\n")
    validate(folder, bsp)
    validate_imx(folder)


def validate(folder, bsp):
    folder = Path(folder)
    if (folder / "uboot-inputs.sha256").read_text() != inputs(bsp):
        raise ValueError("固件输入与当前 04 基线不同，重新 configure/build/package")
    revision = (Path(bsp) / "base-revision").read_text().strip()
    if (folder / "source-revision").read_text().strip() != revision:
        raise ValueError("U-Boot 源码 revision 不一致")
    config = dict(line.split("=", 1) for line in (folder / "uboot.config").read_text().splitlines()
                  if line.startswith("CONFIG_") and "=" in line)
    for key, value in OPTIONS.items():
        if config.get(key) != value:
            raise ValueError(f"固件缺少所需配置：{key}={value}")
    identity = {"policy": 1, "revision": revision,
                "inputs_sha256": sha256(folder / "uboot-inputs.sha256"),
                "config_sha256": sha256(folder / "uboot.config"),
                "image_sha256": sha256(folder / "loader.imx")}
    if json.loads((folder / "firmware.json").read_text()) != identity:
        raise ValueError("固件身份清单不符")
    return identity
