# 05 · 官方 UUU 行为与适配

现有方案已经使用官方 UUU。专用 `emmc-flash.uuu` 在主机运行，板端运行主线 U-Boot 的 fastboot。fastboot 是 USB 烧录协议。官方 `uuu -b emmc` 同样通过 fastboot 写入 eMMC，不能将两者当成互斥路线。

当前限制是板端缺少内置脚本所需的环境约定。raw partition 是按起始扇区、长度和硬件分区描述的写入目标。它不要求修改 DOS 分区表。当前 raw partition 对本板的 boot0 和 1024 字节偏移描述正确。

## 本次取证

调查使用当前主机的 UUU `1.5.21-0-g1f42172`，并核对 [NXP 当前内置脚本](https://github.com/nxp-imx/mfgtools/blob/master/uuu/emmc_burn_loader.lst)。两份脚本内容一致。本地源码基线由 [base-revision](base-revision)固定。本次结果和来源文件见[证据索引](evidence/2026-10-06-uuu-audit/collection.json)。

| 取证项 | 结果 | 依据 |
|---|---|---|
| 默认环境 | 有 `mmcdev=1`，没有 `emmc_dev`、`emmc_ack`、`fastboot_raw_partition_bootloader` | [串口实读](evidence/2026-10-06-uuu-audit/console-audit.log) |
| 启动区域 | MMC 1，硬件分区 1，即 boot0；BOOT_ACK=1 | 同上 |
| 镜像位置 | 第 2 扇区，1024 字节偏移；读出 686 个扇区 | 同上 |
| 镜像内容 | 351232 字节 CRC32=`c48d3a41`，与主机镜像相同 | 同上及证据索引 |
| 原镜像目标查询 | `partition-size:bootloader` 返回 `invalid partition or device` | [UUU 原配置日志](evidence/2026-10-06-uuu-audit/uuu-baseline-file.log) |
| 临时补齐约定后 | 内置脚本的前三条 FB 命令通过；目标容量为 `0xffc00` 字节 | [UUU 适配查询日志](evidence/2026-10-06-uuu-audit/uuu-adapted-query.log) |
| 内置脚本预检 | `uuu -dry -b emmc` 解析当前镜像与脚本，无 Error | [预检日志](evidence/2026-10-06-uuu-audit/builtin-emmc-dry.log) |

临时变量只写入 RAM，测试后已清除。板卡回到 user area 和 1500000 baud 控制台，BOOT_ACK 与启动选择保持原值。本次没有执行 flash、erase、持久启动配置修改或重启。查询成功与 dry run 不等于完整烧录验收。

## 差异来自哪里

官方 `-b emmc` 的 [FB 命令](evidence/2026-10-06-uuu-audit/builtin-emmc.uuu)如下。前面的 SDP 命令负责通过 ROM 将 U-Boot 下载到 RAM。进入 fastboot 后，UUU 执行这些命令：

```text
FB: ucmd setenv fastboot_dev mmc
FB: ucmd setenv mmcdev ${emmc_dev}
FB: ucmd mmc dev ${emmc_dev}
FB: flash bootloader _image
FB: ucmd if env exists emmc_ack; then ; else setenv emmc_ack 0; fi;
FB: ucmd mmc partconf ${emmc_dev} ${emmc_ack} 1 0
FB: Done
```

`emmc_dev` 是设备编号。它与现有 `mmcdev` 不是同一个变量。缺少它时，内置命令不能可靠选择本板设备。主线 fastboot 的实际写入设备由 `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` 固定，脚本设置 `mmcdev` 并不会重定向该配置。

`bootloader` 是板端解释的目标名，UUU 不定义它的物理地址。当前镜像没有默认映射。现有脚本通过 `fastboot_raw_partition_bootloader` 定义目标，使用主线已有的解析与写入实现。见[主线文档](https://docs.u-boot.org/en/latest/android/fastboot.html#raw-partition-descriptors)及本次归档的 [fb_mmc.c](evidence/2026-10-06-uuu-audit/mainline-fb_mmc.c)。

NXP 分支在 [fb_fsl_partitions.c](https://github.com/nxp-imx/uboot-imx/blob/lf_v2025.04/drivers/fastboot/fb_fsl/fb_fsl_partitions.c)中建立专用目标。对 i.MX6ULL，偏移为 `0x400` 字节；具备 boot 分区的 eMMC 使用硬件分区 1。现有脚本在启动选择为 boot0 时，写入同一个位置。原先“raw partition 行为不符，所以无法使用官方 UUU”的结论过度概括。

raw partition 的 `0x2 0x7fe mmcpart 1` 使用 512 字节扇区。写入范围从 1024 字节开始，到 1 MiB 边界前结束，容量为 `0xffc00` 字节。当前 boot0 容量为 4 MiB，这个 1 MiB 边界是本工程的保留范围，并非 UUU 对所有板卡的统一要求。

官方内置脚本固定启用 boot0，并将 PARTITION_ACCESS 切回 user area。缺少 `emmc_ack` 时，它把 BOOT_ACK 设为 0。当前板卡是 BOOT_ACK=1，因此适配时必须显式定义 `emmc_ack=1` 才能维持当前值。现有脚本读取既有启动选择，不主动更换 boot 区域。

当前固件不会自动进入 fastboot。ROM 下载完成后，仍需通过串口执行 `fastboot usb 0`。本工程的 [统一主机脚本](HOST_TOOL.md)在 `emmc` 模式下自动发送这条命令，在 `ram` 模式下保留控制台。即使补齐环境映射，原样 `-b emmc` 也会等待这一步。主机的一条命令与全自动烧录是两个验收目标。

## 两条路线的取舍

| 项目 | 官方 UUU + 当前专用脚本 | 官方 UUU + 原样 `-b emmc` |
|---|---|---|
| 当前验证 | boot0 写入、全量比较、eMMC 启动与 vendor Linux 启动已通过 | 目标查询与主机预检通过，完整烧录未验收 |
| 固件依赖 | 当前主线 fastboot 已满足 | 仍需主线 fastboot，并补默认环境 |
| 写入区域 | 跟随原启动选择，可能是 boot0、boot1 或 user area | 固定写 boot0，并启用 boot0 |
| BOOT_ACK | 保持当前值 | 必须定义 `emmc_ack`，否则使用 0 |
| 写后检查 | 脚本读回并逐字节比较 | 内置脚本没有读回比较 |
| 维护工作 | 工程维护短脚本和本板地址约定 | 板级默认环境维护约定，主机使用内置脚本 |
| 无串口烧录 | 需要自动进入 fastboot 的板级行为 | 同样需要该行为 |
| 使用场景 | 当前移植验证、保留现有系统的维护 | 固定 boot0 的统一交付或量产命令 |

近期继续使用已验收的专用脚本，改动最少。若交付需要统一的 `uuu -b emmc` 命令，建议保留主线 fastboot，补齐板级环境。两条路线可以共用一个 U-Boot 镜像，无需维护独立的 fastboot 固件代码。

## 原样内置脚本的最小适配

以下是适配方案，本次没有修改固件源码或构建新镜像。在 `overlay/include/configs/100ask_imx6ull.h` 的 `CFG_EXTRA_ENV_SETTINGS` 中增加这三项，保留已有配置：

```c
"emmc_dev=1\0" \
"emmc_ack=1\0" \
"fastboot_raw_partition_bootloader=0x2 0x7fe mmcpart 1\0" \
```

`emmc_dev` 与 `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` 必须一致。映射固定到 boot0，匹配内置脚本的最终启动选择。不要在这条路线中将映射动态改成 boot1，却仍让内置脚本最终启用 boot0。

当前 `CONFIG_ENV_IS_NOWHERE=y` 不妨碍使用编译进镜像的默认环境，也不需要增加 `saveenv`。USB gadget、fastboot、MMC flash、UUU UCmd 和 `env exists` 已在当前镜像中启用。无需移植 NXP 的 `fb_fsl` 驱动。

本基线还提供 `CONFIG_FASTBOOT_MMC_BOOT_SUPPORT` 与 `fb_mmc_get_boot_offset()`。默认钩子返回 0 个扇区。仅把 `CONFIG_FASTBOOT_MMC_BOOT1_NAME` 改为 `bootloader`，会从 boot0 的零偏移写入。若采用这条 C 代码路线，还需覆盖钩子返回 2，并复核容量、getvar 和 erase 行为。默认 raw partition 已满足本需求，改动更少。见 [fb_block.c](evidence/2026-10-06-uuu-audit/mainline-fb_block.c)。

第一轮保留手工执行 `fastboot usb 0`，单独验收内置烧录。若需要脱离串口操作，再增加“ROM USB 下载后进入 fastboot，正常 eMMC 启动保持控制台”的板级入口。不要无条件给所有启动路径设置 `preboot=fastboot usb 0`，否则正常 eMMC 启动也会进入 USB 等待。USB 启动来源的判断必须分别在 ROM 下载和 eMMC 启动时实测。

修改 BSP 后，按 [RAM_BOOT.md](RAM_BOOT.md#构建)生成新的源码快照。完整构建由开发者执行。内置脚本使用带 ROM 头的 `u-boot-dtb.imx`，无需为它添加 1024 字节前导填充。raw partition 映射负责物理偏移。

适配镜像构建完成后，在主机产物目录先运行预检。确认默认环境包含上述三项，再执行实际烧录。实际命令会写入 boot0 并设置启动配置：

```sh
cd /home/pi/ea-emb-linux/sdk/bsp_imx/02-uboot-porting/artifacts
sha256sum -c SHA256SUMS
uuu -bshow emmc
uuu -dry -b emmc u-boot-dtb.imx
sudo /var/lib/snapd/snap/bin/uuu -v -b emmc u-boot-dtb.imx
```

板卡从 ROM USB 下载模式启动。若第一轮保留串口入口，在新 U-Boot 提示符执行 `fastboot usb 0`。烧录完成后，检查完整 UUU 日志和启动配置，再独立读回比较、断电启动并引导 vendor Linux。只有这些步骤全部通过，才能将内置命令标为已验收。

## 整盘烧录边界

`-b emmc_all` 与只写 U-Boot 的 `-b emmc` 不同。[内置整盘脚本](https://github.com/nxp-imx/mfgtools/blob/master/uuu/emmc_burn_all.lst)先向 `all` 目标写入系统镜像，再写 bootloader。当前镜像没有启用 `CONFIG_FASTBOOT_MMC_USER_SUPPORT`，也没有定义 `all` raw partition。

后续需要整盘恢复时，可在主线中启用 `CONFIG_FASTBOOT_MMC_USER_SUPPORT=y` 并设 `CONFIG_FASTBOOT_MMC_USER_NAME="all"`，单独验收 user area 与 sparse 写入。sparse 是省略空洞块的镜像传输格式。整盘写入会替换分区表和 rootfs，不能把它作为本次 U-Boot 替换的等价命令。

当前 Snap 启动器会掩盖失败退出码。必须检查 UUU 的 Error、Fail 和每一步结果，不能只看 `$?`。依据是[本机启动器](evidence/2026-10-06-uuu-audit/snap-launcher.sh)，不是板端协议差异。
