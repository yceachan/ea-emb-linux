# 使用现有 02 U-Boot 直接烧录 p2

方案状态：用户已取消 RAM rescue，禁止代理操作板卡；本文件交付开发者审阅的直接烧录路线。开发者已生成并烧录 ext4 镜像，板上 shell 已由用户确认；关闭范围见 [.issues/closed/01-feat-kernel-busybox/close.md](.issues/closed/01-feat-kernel-busybox/close.md)。

使用现有 `rootfs.tar.gz` 制作 1 GiB ext4 分区镜像。kernel、DTB 已包含在 rootfs 的 `/boot`，无需重新编译 kernel、BusyBox 或 U-Boot。

p2 的起始 LBA 为 1028098（`0xfb002`），长度 2097152（`0x200000`）个 512 字节扇区。烧录目标固定为这一范围。该方案重建 p2 文件系统，替代原先保留 ext4 并安装文件树的路线；分区表、p1/p3 和 U-Boot 区域不属于写入目标。

分区依据：`artifacts/2026-10-07-154632-vendor-survey/mmc-layout.txt`。

## 主机制镜像

在工作区执行下面命令，使用已有归档，不运行 SDK 构建。镜像目录必须是新目录。`fakeroot` 使解包的所有者及镜像中的文件元数据保持 root，无需主机管理员权限。

```sh
(
set -eu
cd /home/pi/ea-emb-linux/sdk/bsp_imx/03-kernel-busybox
(cd artifacts/2026-10-07-busybox-r2 && sha256sum --check --strict SHA256SUMS)
mkdir artifacts/emmc-rootfs
cp artifacts/2026-10-07-busybox-r2/rootfs.tar.gz artifacts/emmc-rootfs/
cp emmc-rootfs.uuu artifacts/emmc-rootfs/
cd artifacts/emmc-rootfs
truncate -s 1073741824 rootfs.ext4
fakeroot sh -eu -c '
    mkdir tree
    tar --same-owner -xzpf rootfs.tar.gz -C tree
    mkfs.ext4 -F -b 4096 -m 0 -L rootfs \
        -U 1fd8b4f2-8057-491a-8a6a-24e7ec6a70e8 \
        -O none,has_journal,ext_attr,resize_inode,dir_index,filetype,extent,sparse_super,large_file \
        -E lazy_itable_init=0,lazy_journal_init=0 \
        -d tree rootfs.ext4
'
e2fsck -fn rootfs.ext4
debugfs -R 'stat /bin/busybox' rootfs.ext4
debugfs -R 'stat /boot/zImage' rootfs.ext4
sha256sum rootfs.ext4 emmc-rootfs.uuu > SHA256SUMS
)
```

使用明确的 ext4 特性集合，避免主机默认启用 02 U-Boot 不支持的新特性；沿用已记录的 p2 UUID。检查 e2fsck 退出码为 0、文件 UID/GID 为 0。

[UUU 用法与主机烧录方案](../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## 手工启动与写后验收

02 固件未启用 `sysboot`，`BOOTDELAY=-1` 且环境不持久化。本轮先手工启动；默认自动启动需要后续更新 U-Boot。

```text
mmc dev 1 0
ext4load mmc 1:2 0x84000000 /boot/zImage
ext4load mmc 1:2 0x83000000 /boot/imx6ull-100ask-pro.dtb
setenv bootargs console=ttymxc0,1500000n8 root=/dev/mmcblk1p2 rootfstype=ext4 rootwait rw
bootz 0x84000000 - 0x83000000
```

每个加载命令成功后再继续。系统启动后检查 kernel 为 `7.2.9-100ask-pro`、PID 1 为 `/bin/busybox`、根挂载为 eMMC p2 的 rw ext4，并在 `/boot` 执行 `sha256sum -c SHA256SUMS`。板上 shell 已确认可用；上述身份、校验和及专项检查的记录边界见 close.md。
