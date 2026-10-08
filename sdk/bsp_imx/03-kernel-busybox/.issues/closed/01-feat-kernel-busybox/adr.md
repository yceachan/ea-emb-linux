# 技术决策（已归档）

当前部署约束（2026-10-07）：用户已取消并删除 RAM rescue，代理不得操作板卡。BusyBox 与 rootfs 工作区统一到 `rootfs/`。直接烧录 p2 ext4 镜像的方案由 [DEPLOY.md](../../../DEPLOY.md) 维护，涉及重建 p2 文件系统；旧文中的 RAM rescue/文件树安装路线不再执行。用户已确认直接镜像实物烧录及板上 shell 完成，关闭范围见 [close.md](close.md)。

状态：2026-10-09 随 issue 关闭归档。最终交付采用 p2 ext4 分区镜像；自动引导移交 04。早期 RAM rescue 提案保留为历史决策，最终范围由 [close.md](close.md) 维护。

## ADR-01 · 源码基线与移植输入

目标内核确定沿用本地 Linux 7.2.9。建议 BusyBox 1.36.1 使用现有 prebuilt ARM hard-float 工具链，并固定提交。当前本地提交分别为：

- Linux：`5fce161649b4d779d1b76d9fcd52dc77779774b8`。
- BusyBox：`1a64f6a20aaf6ea4dbba68bbfa8cc1ab7e5c57c4`。

这里记录本地源码身份，后续构建固定上述提交。

沿用上一阶段的源码快照、板级 overlay/patch 和独立输出目录方式。上游 SoC DTSI、驱动和绑定作为目标内核的依据，vendor 4.9 DTS 提供板级接线参考。内核配置从现有 `imx_v6_v7_defconfig` 起步，增加实际启动所需配置，再固化本板输入。

本轮内核、板级 DTB 和 BusyBox rootfs 已形成构建产物；用户确认烧录并进入板上 shell。构建记录与实板确认的来源见 [close.md](close.md)。

## ADR-02 · 全外设 DTB 与最小启动验证

维护一个本板 DTS 入口，逐步补齐板级描述；同一硬件接线不维护两份独立事实来源。最终最小外设验收使用同一交付 DTB。2026-10-07 用户确认默认选择已连接 LCD，HDMI 启用留待后续对齐，因此当前不再以 LCD/HDMI 同时可用作为本阶段目标，也不将禁用 HDMI 记为其功能移植完成。

先审查 memory、UART1、USDHC2，以及其时钟、pinctrl、中断和供电依赖，再逐项迁移其他板级外设。vendor 文件的自定义属性、旧绑定、320 MiB CMA 预留和复用关系均需依据目标内核及实际硬件重新判断。显示等功能未明确前，不机械继承大额 CMA。

全外设清单以现有 `100ask_dts/dts_readme.md` 为调查起点，核对 DTS 与可用原理图；其中未确认接线不能当作已证实事实。没有目标绑定或驱动支持的项单独列出，评估采用主线绑定、移植必要支持或调整里程碑范围，并与用户对齐后执行。

不引入 DT overlay 管理框架或动态外设选择。若某个非最小外设导致最终 DTB 无法启动，先定位具体依赖或引脚冲突；需要延后该项时重新商定范围。板级输入与逐项迁移结果由工作区 `PORTING.md` 维护，不在本 ADR 复制资源清单。新发现的 AP3216C 驱动/绑定缺口及 Wi-Fi/4G 功能已获确认留后续；供电描述差异继续保留，未核实前不启用新的电源控制。

板级迁移项、目标绑定、驱动配置及资料缺口统一见工作区 [PORTING.md](../../../PORTING.md)。当前输入已采用标准 Goodix、SPI GPIO、74HC595、WM8960/ASRC 与 PXP 描述；完整配置解析与内核构建仍需开发者执行，不能从 defconfig 的声明直接推断驱动已进入最终产物。

### 引脚组合与实板结论

已连接的屏幕为 1024×600，实板控制器识别为 GT911（固件 1060），经 I²C2 地址 0x5d 通信。`goodix-ts` 已注册 event1；用户操作产生了坐标、按下/抬起和多触点 slot 事件。默认硬件组合按这条电容触摸通路确定，片内电阻触摸 TSC 禁用。

以下接口编号来自本地 V1.1 底板原理图第 2、5、7 页；对应资源归属已与实板 DT、pinmux 和驱动核对。原理图图框标为 STD，PRO V11 丝印图中也包含对应的 U7、R63、J5、J8；丝印本身不作为网络连接的证据。

| SoC pad | 核心板 U1 脚 | TSC 四线功能 | 图示引出 | 实板 pinmux 归属 |
|---|---|---|---|---|
| GPIO1_IO01 | 42 | Y- / YNLR | R63（0 Ω）→ U7 ICM20608 INT | ECSPI3 |
| GPIO1_IO02 | 43 | Y+ / YPLL | ADC1_CH2 → LCD J8-49，LCD ID | 未被 pinmux 申请 |
| GPIO1_IO03 | 44 | X- / XNUR | ADC1_CH3 → CAMERA J5-10，标为 ADC1 | ADC |
| GPIO1_IO04 | 45 | X+ / XPUL | ADC1_CH4 → CAMERA J5-12，标为 ADC2 | ADC |

TSC 功能依据参考手册表 53-1、53-6。J5 的 ADC1/ADC2 是连接器脚名，实际为 SoC ADC1 的通道 3/4。TSC 驱动使用 ADC2 寄存器；冲突发生在共用的外部 pad，不是两个驱动使用同一 ADC1 控制器。

ICM20608 的 SPI 时钟、MOSI、MISO 使用 UART2 焊盘复用出的 ECSPI3，片选使用 GPIO1_IO20。与 TSC 重叠的是 IO01 中断脚。vendor TSC 已因 IO01 被 ECSPI3 请求而 probe 失败（-22），没有注册触摸输入设备。ICM20608 与 ADC 均已注册 IIO，本轮未进行采样功能验证。

LCD J8-45～48 虽标为 XR/XL/YD/YU，但底板和配套转接板图均为 NC。已连通的触摸路径是 J8-35 INT（GPIO1_IO05）、J8-36 RESET（GPIO5_IO02）、J8-37/38 I²C2 SCL/SDA，经转接板连到 6 针触摸 FPC J3。实板 GPIO1_IO05 和 GPIO5_IO02 均由 I²C `1-005d` 的 GT911 驱动占用。

LCDIF 实际模式为 1024×600。GT911 内部有效配置也是 1024×600，但 vendor DT 和 input ABS 范围声明为 800×480。移植使用 `goodix,gt911`，按 1024×600 核对主线驱动坐标范围，不复制旧的 800×480 声明。本轮已验证基本触摸事件，全屏边缘坐标与方向尚未验收。

证据索引：`artifacts/2026-10-07-pin-audit/sources.json`（图纸）与 `artifacts/2026-10-07-154632-vendor-survey/collection.json`（实板）。

## ADR-03 · BusyBox rootfs 与落盘

用户确认直接构建 BusyBox 1.36.1 的静态二进制，使用 BusyBox init、ash、显式 `inittab` 与 `rcS`。当前工具链能够定位 `libc.a` 和 `libm.a`，静态链接仍需实际构建和 ELF 检查确认。静态方案减少本阶段动态加载器与共享库部署变量；本阶段暂不引入 Buildroot 的整套系统构建。

最终 rootfs 使用 eMMC user area 中的 ext4 文件系统，`/boot` 是该 rootfs 内的目录。内核直接挂载 ext4 rootfs，因此 MMC、USDHC、分区解析、ext4 和启动所需依赖必须内建。本次实测原 rootfs 为 `/dev/mmcblk1p2`，起始 LBA 1028098，长度 2097152 个 512 字节扇区，即 1 GiB。MBR 磁盘签名为零，导出的 PARTUUID 为 `00000000-02`。本阶段保持分区表，内核 DTS 保留 USDHC2 的 `mmc1` alias，启动参数采用 `root=/dev/mmcblk1p2 rootwait rw`，并在主线首次启动时核实枚举结果；不为获得唯一 PARTUUID 额外修改 MBR。

用户决定直接替换 vendor rootfs，不做备份，恢复来源为网盘中的出厂镜像。沿用当前 rootfs 分区，不新增分区或改写分区表；分区边界已由 sysfs、分区表及 MBR 读取交叉确认，部署前复核目标设备。出厂镜像未在本轮检查，恢复不标为已实测。

### 已选择的 RAM 救援部署路线

用户选择 RAM 救援环境部署文件树。建议救援使用本轮内核、同一板级 DTB 和外部 gzip cpio initramfs；救援包包含静态 BusyBox、`/init`、明确的安装脚本和最终 `rootfs.tar.gz`。最终归档设计包含 `/boot/zImage`、DTB 与 extlinux 配置，所有者固定为 root，保留可执行权限和符号链接。救援启动后先进入串口 shell，开发者核实设备与分区后执行安装脚本。

具体文件系统处置提案：保留原 p2 上的 ext4，不格式化。在救援环境确认 `/` 位于 RAM、p2 未被其他路径挂载，并复核起始 LBA 1028098、长度 2097152 后，单独挂载 p2；清除旧系统目录，保留文件系统自身的 `lost+found`，再展开经过校验的新文件树。写入后同步、检查关键文件内容/权限、卸载，再从 U-Boot 手工启动目标系统。这样分区表、文件系统 UUID 和特性不变，也不需要额外交叉构建板端 `mkfs.ext4`。挂载或文件系统检查发现错误时停止，不用覆盖文件掩盖故障。

这是完整替换旧系统文件，不是覆盖拷贝几个文件；清除或展开中断后该 rootfs 可能无法启动，应重入 RAM 救援重新部署，不将它描述为原子更新。按已授权策略不增加备份步骤。

[UUU 用法与主机烧录方案](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

候选 RAM 布局为 kernel `0x84000000`、DTB `0x83000000`、救援 cpio `0x88000000`；下载临时区仍为 `0x82000000`。使用前核对本轮解压后的 ARM Image/BSS/工作空间、`bdinfo` 的 U-Boot relocation/栈/堆、LMB 及文件实际长度。布局核验未完成；该救援路线已撤销。

initramfs 用于离线部署；目标默认系统依然直接挂载 eMMC ext4，不依赖救援包。内核片段显式要求 `BLK_DEV_INITRD` 与 `RD_GZIP`，外部 initramfs 行为见[内核说明](https://docs.kernel.org/filesystems/ramfs-rootfs-initramfs.html)。

## ADR-04 · `/boot` 配置与默认引导

本节记录 03 阶段的自动引导提案，实际交付使用已有 U-Boot 手工启动。后续自动引导由 [04 issue](../../../../04-br-rtfs-integration/.issues/open/01-feat-br-system/issue.md) 按其新固件与布局实现。

用户确认使用 `/boot/extlinux/extlinux.conf`，将 `DEFAULT` 指向 `busybox` 标签，显式指定 `/boot/zImage`、`/boot/imx6ull-100ask-pro.dtb` 和 root 分区参数。文件输入在工作区 `rootfs/overlay/boot/extlinux/extlinux.conf`，已包含在 rootfs 镜像中。extlinux 配置格式与内核、DTB 的指定方式见 [U-Boot 文档](https://docs.u-boot.org/en/latest/develop/distro.html)。

现有 U-Boot 关闭 Boot Standard，选择增加 `CONFIG_CMD_SYSBOOT`，由编译进镜像的默认 `bootcmd` 从明确的 eMMC user area 第 2 分区读取配置。命令失败后留在可诊断的控制台。基线 `cmd/sysboot.c` 接受的文件系统参数为 `ext2`，对应 EXT 文件系统实现，也读取 ext4；不要误写成不被此版本接受的 `ext4` 参数。

候选入口如下。地址属于待核验布局，不是已实板通过的配置：

```text
kernel_addr_r=0x84000000
fdt_addr_r=0x83000000
pxefile_addr_r=0x83200000
bootcmd=mmc dev 1 0 && sysboot mmc 1:2 ext2 ${pxefile_addr_r} /boot/extlinux/extlinux.conf
```

`kernel_addr_r` / `fdt_addr_r` 是 sysboot 消费的变量，原有 `fdt_addr` 不能替代 `fdt_addr_r`。不传 `-p`，extlinux 输入使用 `PROMPT 0` / `TIMEOUT 0`；交互等待只由 U-Boot 的 3 秒 `bootdelay` 提供，避免二次倒计时。保留手工 `bootz` 故障定位入口。

启动入口继续使用 `ENV_IS_NOWHERE`，默认行为随 U-Boot 镜像固定；日常修改默认系统标签在 extlinux 文件内完成，本阶段无需新增持久环境分区。用户确认可中断的 3 秒自动启动等待时间。U-Boot 的源码与配置修改仍在 `02-uboot-porting` 维护，本工作区维护 rootfs 的 `/boot` 文件，避免复制已完成的移植工程。先完成手工目标系统验收，再接入和写入默认启动固件。

备选是开启 Boot Standard/extlinux bootmeth，让 U-Boot 扫描启动介质。它适合后续多介质发现需求；当前只有指定 eMMC 启动目标，建议先使用显式 `sysboot`。两种方式都需要实际构建与冷启动验证。

vendor rootfs 已确定替换，菜单只需包含 BusyBox 项。本阶段不维护 vendor 菜单项或双系统启动。

## ADR-05 · 串口与 DDR 验证边界

建议保留现有 U-Boot 的 1500000 baud，将新内核 DT `stdout-path`、kernel `console=ttymxc0,1500000` 和用户空间串口统一到该速率，减少自动引导中的串口切换。目标内核该速率须实测；若出现具体驱动或主机适配问题，再根据结果调整。

DDR 初始化继续由现有 DCD/U-Boot 完成。Linux 配置 512 MiB 的实际地址范围，保留区均需明确依据。内存验证先检查内核内存布局，再进行有限的分配、写入和读回测试；不能从 Linux 的 `MemTotal` 直接要求等于 512 MiB，也不能在运行系统中用裸地址写入覆盖已占用内存。ARM 启动时内存初始化及 DT 传递职责见 [内核启动约定](https://docs.kernel.org/arch/arm/booting.html)。

默认采用可重新进入的串口调试 shell；正常 PID 1 为 BusyBox init。将 `/bin/sh` 临时作为 PID 1 只用于定位，不计入最终 rootfs 完成状态。

## ADR-06 · BusyBox 集成目标

状态：BusyBox 配置、启动文件和 rootfs 打包输入已交付，目标镜像已烧录并进入板上 shell；RAM rescue 已取消。运行与构建方法由工作区 [rootfs/README.md](../../../rootfs/README.md) 维护。

### 构建与文件组织

固定 ADR-01 的 BusyBox 提交，使用工程现有 ARM hard-float 工具链。从 `allnoconfig` 选入目标启动、诊断和救援安装需要的 applet 与子功能，交付最终解析配置。编译一次静态 BusyBox，目标 rootfs 与救援环境复用相同二进制；核对 ARM ELF、链接属性、applet 清单、符号链接与执行权限。完整编译由开发者执行，沿用 `-j12`。

正常 rootfs 维护 BusyBox 安装树、`/etc/inittab`、`/etc/init.d/rcS`、shell 环境、root 用户信息及 `/boot` 文件。救援文件树复用已选 BusyBox 和适用的初始化文件，另加 `/init`、安装脚本、目标归档与校验清单。设备节点通过打包清单表达，使救援启动前已有 `/dev/console` 和 `/dev/null`；打包 UID/GID 固定为 0，不要求主机执行 root 权限下的整套构建。

### 首轮命令范围

用户确认首轮只覆盖启动、文件操作和板级诊断。具体 applet 清单随配置固化，按以下实际用途选择：

| 用途 | 必需能力 |
|---|---|
| 初始化与交互 | init、ash/sh、mount、umount、hostname、stty、reboot/poweroff；shell 支持交互和作业控制 |
| 文件与脚本 | ls/cat/cp/mv/rm/mkdir、ln/chmod、find、grep/sed、test、printf、sleep；以启动及安装脚本的实际调用为准 |
| 板级诊断 | uname、dmesg、ps、free、df、du、hexdump、dd、sync、sha256sum；可查看 proc/sysfs 中的设备、内存与挂载信息 |
| 救援安装 | tar 解包、gzip 解压、校验清单检查，保留归档中的权限/所有者/符号链接；安装前检查所需工具与数据完整性 |

本阶段不自动配置网络，不启动网络服务；网口/DHCP/ping 命令也不列入当前验收。DDR 数据测试另按 issue 的测试范围落实，`free` 只检查内存信息，不能用它声称 DDR 读写测试通过。

### 目标系统启动行为

用户确认串口直接进入 root 调试 shell，不设登录环节，使用 `ttymxc0`、1500000 baud、8N1；正常 PID 1 为 BusyBox init。inittab 显式将 shell 绑定到该 tty 并设置 respawn，避免借用 `/dev/console` 后缺少控制终端。验收应包括命令输入/输出、Ctrl-C、前后台作业和退出后重新进入。

rcS 负责 proc、sysfs、`/run` 和 `/tmp` 挂载及基础环境。正常 eMMC 启动已由内核 `DEVTMPFS_MOUNT` 挂载 `/dev`；救援的 `/init` 显式挂载 devtmpfs 后 exec BusyBox init，使两条入口都能使用动态设备节点。`/run`、`/tmp` 放在 tmpfs 中，其内容不要求重启保留；eMMC rootfs 使用 rw，正常文件写入经同步与重启后应保留。

必要挂载或初始化失败时输出具体步骤与错误，并停在串口维护路径；不打印正常启动完成提示。BusyBox 1.36.1 的 init 等待 sysinit 进程结束，但不会以其非零退出码自动阻止 respawn，因此不能仅依靠 `set -e` 就宣称故障阻断已完成。保持 PID 1 存活，失败路径不退出到内核。

### 救援环境与部署行为

救援使用相同内核/DTB和独立外部 initramfs。启动后必须能区分当前是 RAM 救援环境，先进入串口 shell；不在 `/init` 或 rcS 中自动清除或安装 eMMC 文件。先确认 kernel 身份、BusyBox PID 1、控制终端、MMC 枚举及 RAM 根，再执行明确的安装命令。

安装命令先核对目标设备/分区边界、挂载状态、归档校验和可用容量，再开始清除旧系统文件。安装只写 user area 的 p2 文件树；分区表、boot0/boot1、p1/p3 不属于其写入目标。具体部署与中断恢复行为由 ADR-03 维护，不建立第二套独立事实来源。

### 阶段交付与验收

交付固定配置与构建命令、目标 rootfs 文件树及 tar 归档、救援 cpio.gz、部署脚本和文件校验清单。kernel/DTB 取自已复核的本轮产物，归档 `/boot` 与实际启动文件保持一致。打包后核验实际文件长度与解压内存布局；不以估算替代检查。

首先只启动 RAM 环境，证明本轮内核与 BusyBox 用户空间能运行；随后离线部署 p2，再手工从 eMMC 启动，验证 PID 1、必要挂载、tty 行为、文件持久化及 `/boot` 一致性。RAM 启动通过不能代替最终 eMMC 验收；默认自动启动按 R4 最后接入。
