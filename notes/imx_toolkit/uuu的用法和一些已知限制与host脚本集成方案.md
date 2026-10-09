---
title: UUU 的用法、已知限制与 host 脚本集成
tags: [i.MX6ULL, UUU, U-Boot, eMMC]
note_types: document
created: 2026-10-09
updated: 2026-10-10

---


# UUU 的用法、已知限制与 host 脚本集成

> [!NOTE]
> 当前 U-Boot 基础层需求已转到 [04 U-Boot 专章](../../sdk/bsp_imx/04-br-rtfs-integration/.issues/open/02-feat-uboot-foundation/issue.md)：仅当前板卡、MBR/ext4、外部描述及产品 target hash 一致免擦写。本文保留协议原理与历史 FAT32/项目化方案审查，不据其冻结新布局、路径或操作接口。

UUU 通过芯片 ROM 将 U-Boot 下载到 RAM，再通过 U-Boot 的 fastboot 接口写入 eMMC。本文以 100ask i.MX6ULL Pro 为例，说明协议与镜像的关系、CLI 和脚本用法、板端适配要求，以及主机脚本如何组织烧录。工具原理与历史版本核对见正文；04 软件实现状态已更新至 2026-10-10，主机检查不代替实板验收。


## 1. 基本原理

### 1.1 ROM 下载与 fastboot 烧录

完整烧录由 ROM 下载和 fastboot 写盘两个阶段组成。

第一阶段由芯片的 Boot ROM 接收镜像。开发者将板卡切换到 USB 下载模式后，ROM 通过 SDP（Serial Download Protocol）与主机通信。UUU 将适配本板的 U-Boot 下载到 RAM，再让 ROM 跳转执行它。

第二阶段由 U-Boot 写入 eMMC。U-Boot 启动 fastboot USB 接口后，UUU 将待烧录的数据发送到它的下载缓冲区，并指定写入目标。U-Boot 根据目标名称选择 eMMC 区域，执行写入；如果收到的是 Sparse 镜像，还会先解码镜像中的数据块。ROM 下载接口和 fastboot 接口之间会发生一次 USB 重新枚举。[NXP 项目说明](https://github.com/nxp-imx/mfgtools)

### 1.2 loader 与产品 U-Boot

运行在 RAM 中的 U-Boot 负责本次烧录，称为 **loader**；写入 eMMC、供以后上电启动的 U-Boot 是产品镜像。两者可以使用同一个文件，也可以分别提供。loader 需要具备本板的 DDR、USB、eMMC 和 fastboot 支持。

### 1.3 `.imx` 镜像结构与构建

在 i.MX6ULL 上，ROM 通过 `.imx` 镜像中的启动结构找到 U-Boot。镜像包含 IVT（入口地址和结构指针）、Boot Data（加载地址和长度）以及 DCD（寄存器初始化表）。ROM 先按 DCD 配置时钟和 DDR，再加载并执行 U-Boot。

U-Boot 构建会生成几个不同用途的文件：

| 文件 | 内容 |
|---|---|
| `u-boot` | ELF 文件，包含链接、符号和调试信息 |
| `u-boot.bin` | U-Boot 二进制 |
| `u-boot-dtb.bin` | 带 U-Boot 设备树的二进制 |
| `u-boot-dtb.imx` | 由 mkimage 加入 i.MX ROM 启动结构的镜像 |

本工程已经配置了这条生成链：[04 板级 Kconfig](../../sdk/bsp_imx/04-br-rtfs-integration/uboot/overlay/board/100ask/imx6ull/Kconfig) 选择 `imximage.cfg`，构建规则先预处理配置，再用 mkimage 封装二进制。配置中记录了镜像版本、启动介质和 DCD，入口地址由 `CONFIG_TEXT_BASE` 指定。

在已配置并加载交叉工具链的构建环境中，开发者可以生成并查看镜像：

```sh
make -j12 u-boot-dtb.imx
tools/mkimage -l u-boot-dtb.imx
```

## 2. CLI 与脚本用法

### 2.1 命令形式

命令中的 `loader.imx` 指负责烧录的 U-Boot，`product.imx` 指准备写入 eMMC 的 U-Boot，`system.raw.img` 指包含分区表和系统文件的原始整盘镜像（raw）。

| 命令 | 用途 |
|---|---|
| `uuu loader.imx` | 通过 ROM 下载并运行启动镜像 |
| `uuu -b emmc loader.imx product.imx` | 启动 loader，再将 product.imx 写入 bootloader 目标；省略第二个文件时写入 loader 本身 |
| `uuu -b emmc_all loader.imx system.raw.img` | 启动 loader，写入整盘系统镜像，再将 loader 写入 bootloader 目标 |
| `uuu task.uuu` | 执行指定的烧录脚本 |
| `uuu -dry task.uuu` | 解析脚本并检查输入文件，供正式执行前预检 |

`-b` 调用的是 UUU 内置脚本。`emmc` 用于更新 U-Boot，`emmc_all` 用于写入完整系统。内置脚本随工具版本发布，可以用 `-bshow` 查看实际步骤。[emmc 脚本](https://github.com/nxp-imx/mfgtools/blob/uuu_1.5.21/uuu/emmc_burn_loader.lst)、[emmc_all 脚本](https://github.com/nxp-imx/mfgtools/blob/uuu_1.5.21/uuu/emmc_burn_all.lst)

### 2.2 查询命令与运行参数

```sh
uuu -h
uuu -H
uuu -bshow emmc
uuu -bshow emmc_all
```

`-h` 显示版本和基本参数，`-H` 显示协议命令的详细帮助。常用运行参数如下：

| 参数 | 用途 |
|---|---|
| `-v` | 输出详细执行日志 |
| `-m <USB路径>` | 指定目标设备的 USB 拓扑路径，适合同时连接多块板卡的主机 |
| `-t <秒>` | 设置等待已知 USB 设备出现的时限 |
| `-T <秒>` | 设置等待下一启动阶段设备出现的时限 |
| `-lsusb` | 列出工具识别的 USB 下载设备 |
| `-udev` | 输出用于配置 USB 访问权限的 udev 规则 |

### 2.3 `.uuu` 脚本与协议命令

`.uuu` 文件按顺序描述下载和烧录步骤。`uuu_version` 声明脚本要求的工具版本，命令前缀指定协议阶段：本板的 `SDP:` 命令与 ROM 通信，`FB:` 命令与 U-Boot fastboot 接口通信。

| 命令 | 作用 |
|---|---|
| `SDP: dcd -f <镜像>` | 由 ROM 执行镜像中的 DCD，初始化 DDR |
| `SDP: write -f <镜像> -ivt 0` | 将启动镜像下载到 RAM |
| `SDP: jump -f <镜像> -ivt 0` | 跳转执行启动镜像 |
| `FB: download -f <文件>` | 将文件送入 fastboot 下载缓冲区 |
| `FB: ucmd <命令>` | 通过 UUU 扩展调用 U-Boot 命令 |
| `FB: flash <目标> <文件>` | 下载文件并请求 U-Boot 写入指定目标 |
| `FB: Done` | 标记本次主机任务结束 |


## 3. 板端目标映射与 i.MX6ULL 适配

UUU 将 `bootloader`、`all` 等目标名称传给 U-Boot，由 U-Boot 将名称映射到存储区域。主线 U-Boot 支持逻辑分区、分区别名和 raw partition descriptor（直接指定起始扇区、长度和硬件分区）。[主线 fastboot 文档](https://docs.u-boot.org/en/latest/android/fastboot.html)

### 3.1 eMMC 硬件分区与逻辑分区

本板 eMMC 接在 USDHC2，U-Boot 的 MMC 设备编号为 1。它包含以下硬件区域：

| 硬件分区编号 | 区域 |
|---|---|
| 0 | 用户数据区（user area），分区表和 Linux 系统所在区域 |
| 1 | boot0 |
| 2 | boot1 |

Linux 的 `mmcblk1p2` 表示 user area 中的第 2 个逻辑分区。它与上表中的硬件分区 2 分别属于分区表和 eMMC 控制器的编号体系。

### 3.2 bootloader 偏移与 raw 描述

NXP 对 i.MX6ULL 使用`0x400` 字节的 bootloader 起始偏移。04 基线将 `bootloader` 映射到 boot0，并沿用已有的 1 MiB 保留范围：[NXP 实现](https://github.com/nxp-imx/uboot-imx/blob/lf_v2025.04/drivers/fastboot/fb_fsl/fb_fsl_partitions.c)

```text
fastboot_raw_partition_bootloader=0x2 0x7fe mmcpart 1
```

这段描述以 512 字节为一个扇区：起点是第 2 扇区，长度为 `0x7fe` 个扇区，目标为硬件分区 1。镜像从 boot0 的 1024 字节处开始写入，最多占用 `0xffc00` 字节。写入偏移由这个映射提供，交付的 `.imx` 文件保持构建时的内容。

### 3.3 默认环境与整盘目标

新基线的 fastboot 写入设备由 `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` 选择，`bootloader` 使用上一节的 boot0 映射。整盘目标 `all` 通过以下配置提供：

```text
CONFIG_FASTBOOT_MMC_USER_SUPPORT=y
CONFIG_FASTBOOT_MMC_USER_NAME="all"
```

独立 rootfs 更新使用 `fastboot_partition_alias_rootfs=1.0:2`，将 `rootfs` 解析到 MMC 1 的 user area 第 2 个逻辑分区。kernel 和 DTB 使用第 6 节的文件更新方式。自制脚本直接指定 MMC 1 和 boot0 启动设置。

04 板级配置已加入上述默认映射、`all` 支持及 FAT 读写能力。板级对象、设备树及 U-Boot ELF 检查通过，产品 .imx 构建与实板映射验证仍待完成。

### 3.4 fastboot 启动入口

新基线提供两条启动路径：通过 ROM USB 下载进入 RAM 的 loader 自动运行 `fastboot usb 0`；从 eMMC 启动的产品 U-Boot 自动加载启动分区中的 kernel 和 DTB，再启动 Linux，由 Linux 挂载 p2 中的 rootfs。

开发者将板卡设为 USB 下载模式并启动主机脚本后，脚本完成 RAM 下载，loader 负责进入 fastboot，整个过程无需手工在串口输入命令。现有 `02` 固件仍停在串口控制台；04 的两条自动启动配置已实现，USB 路径采用上游 i.MX6UL 的 PHY 状态检测。启动路径的选择仍须按本板实际 ROM 启动信息验证，分别覆盖 USB 下载和 eMMC 冷启动。

## 4. Sparse 镜像

### 4.1 块类型与写入语义

整盘 raw 镜像通常包含大量空白区域。Android 使用的 AOSP Sparse 格式用块记录描述镜像，将连续数据、重复值和可跳过区域分别编码，减少传输数据量。

| 块类型 | U-Boot 的处理方式 |
|---|---|
| RAW | 将记录中的数据写入目标 |
| FILL | 将指定值重复写入目标，例如用很少的传输数据表示一大段零值 |
| DONT_CARE | 跳过对应的逻辑块，保留介质中的原有内容 |

FILL 节省 USB 传输量；DONT_CARE 同时省去对应区域的写入。镜像中的分区表、文件系统元数据和已分配文件内容应保留完整，包括其中有意义的零值。文件系统空闲块和分区间留白可以按镜像布局标记为可跳过区域。

### 4.2 主机生成与校验

主机文件系统也支持稀疏文件：文件具有完整逻辑长度，空洞区域按零读取，却只为实际数据占用空间。支持 hole 模式的 AOSP img2simg 可以将这些空洞转换成 Sparse 中的跳过范围：

```sh
img2simg -s system.raw.img system.sparse.img 4096
simg2img system.sparse.img system.expanded.img
```

`-s` 使用主机文件的空洞信息，`4096` 指定镜像块大小。制作和复制 raw 镜像时，需要按前述数据范围保留正确的空洞；转换完成后，可展开镜像检查分区布局、文件系统和有效数据。[img2simg 实现](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/img2simg.cpp)

如果输入是 ext4 分区镜像，可以用 ext2simg 从文件系统的块分配位图中识别已分配块，再生成 Sparse。选定工具时，应检查它对目标 ext4 特性的支持。本地 Buildroot 提供的是早期 Android 工具，现代 img2simg 的 `-s` 参数需要另行核对。[ext2simg 实现](https://android.googlesource.com/platform/system/extras/+/android-4.2.2_r1/ext4_utils/ext2simg.c)

本轮已检测到本机 `/usr/bin/img2simg` 和 `/usr/bin/simg2img`；独立解码器用于交叉检查 04 编码器。Fedora 44 的 `android-tools` 包提供这两个程序，新主机可据此准备。[Fedora 包文件清单](https://packages.fedoraproject.org/pkgs/android-tools/android-tools/fedora-44.html)

```sh
sudo dnf install android-tools
```

若选择通用 hole 转换路线，安装后先用带空洞的小型 raw 镜像验证 `img2simg -s`：检查转换结果包含对应的 DONT_CARE 范围，再用 simg2img 展开并比较有效内容。AOSP Android 15 的参考源码已支持该参数；Fedora 实际二进制的行为以这项检查为准。工具通过后记录包版本及程序 SHA-256，供镜像制作入口预检。04 的实际封装使用 `uboot/package.py` 与 `uboot/tools/images.py`：genimage 组装 raw 后，由 e2fsprogs 的空闲块清单确定可跳过范围，直接编码 AOSP Sparse。MBR 和 FAT 完整保留，ext4 已分配块中的零值仍写入，不依赖主机文件空洞。编码器已通过独立 simg2img 的 RAW/FILL/DONT_CARE 解码检查；展开后还检查文件系统与位图覆盖。通用 img2simg 示例仍可用于其他已正确构造空洞的镜像，不是 04 包制作的实际命令。

### 4.3 UUU 传输入口

#### 4.3.1 预制 Sparse

预制 Sparse 使用普通 flash 命令：

```text
FB: flash all system.sparse.img
```

UUU 1.5.21 已支持预制 Sparse 的识别与分块传输。

#### 4.3.2 raw 镜像

raw 镜像使用 raw2sparse 入口：

```text
FB: flash -raw2sparse all system.raw.img
```

`-raw2sparse` 在主机上将 raw 数据转换成 Sparse 再发送。内置 `emmc_all` 使用的就是这个命令。

#### 4.3.3 raw 镜像与 bmap

UUU 1.5.21 的 raw2sparse 根据数据内容压缩重复值。若要按 raw 镜像的有效块跳过空闲区域，可使用支持 bmap 的 UUU 版本。bmap 文件记录需要传输的块，新版本通过 `-bmap` 尝试读取它；主机脚本负责检查映射存在且与镜像匹配。[UUU 1.5.243 参数实现](https://github.com/nxp-imx/mfgtools/blob/uuu_1.5.243/uuu/uuu.cpp)

```sh
uuu -bmap -b emmc_all loader.imx system.raw.img
```

## 5. 已知限制与版本要求

### 5.1 下载缓冲区与分块传输

本板当前 fastboot 缓冲区为 16 MiB。UUU 对预制 Sparse 的 flash 操作会按板端报告的容量拆分传输，每段都保留原镜像的逻辑偏移，因此整盘镜像可以大于下载缓冲区。

单次 `FB: download` 将文件送入下载缓冲区，受本板 16 MiB 容量限制。用于 flash 的 Sparse 分块传输和用于 RAM 启动的文件加载，需要分别安排。

### 5.2 预制 Sparse 与 raw2sparse 的兼容性

UUU 1.5.21 和 1.5.243 的 raw2sparse 路径会将输入文件按 raw 数据处理。如果输入已经是 Sparse，工具会再次包装这个文件，使板端写入 Sparse 容器本身的字节。预制 Sparse 因此使用 `FB: flash all system.sparse.img`，由普通 flash 路径识别并分块发送。[1.5.21 实现](https://github.com/nxp-imx/mfgtools/blob/uuu_1.5.21/libuuu/fastboot.cpp)、[1.5.243 实现](https://github.com/nxp-imx/mfgtools/blob/uuu_1.5.243/libuuu/fastboot.cpp)

### 5.3 预检范围与结果判断

`-dry` 检查主机上的脚本和文件。MMC 编号、分区映射、USB 阶段切换及写入结果，要在板端执行后才能验证。主机脚本可以在调用 `-dry` 前增加校验和、镜像布局和容量检查，统一对外提供 `--dry-run` 入口。

主机脚本应分别记录设备等待时限和烧录总时限。UUU 的 `-t`、`-T` 处理设备出现和阶段切换，主机脚本另外管理完整任务的超时。

本机旧 Snap 曾出现 UUU 报错后启动器仍返回零的情况。因此主机脚本同时检查进程退出码、失败文本和各阶段的成功记录。现有分区镜像部署脚本用伪终端运行 UUU，使等待提示和传输进度能够实时显示，并同步写入日志。

### 5.4 Snap 版本与可选升级

当前 Snap 包 `universal-update-utility` 安装的是 1.5.21。2026-10-09 查询到的 Store stable 为 1.5.21，edge 为 1.5.141。预制 Sparse 路线可以使用现有版本；raw＋bmap 路线可从 NXP 官方发布页另装已核对的 1.5.243，并由主机脚本固定可执行文件路径。[Snap Store](https://snapcraft.io/universal-update-utility)、[NXP 官方发布](https://github.com/nxp-imx/mfgtools/releases/tag/uuu_1.5.243)

## 6. host 脚本层集成

### 6.1 职责划分

主机脚本负责把镜像检查、板卡准备、UUU 执行和写后验证串成一个入口。UUU 负责 USB 协议，U-Boot 负责 eMMC 操作。

### 6.1.1 独立部署 eMMC U-Boot

04 提供 `uboot/flash.py bootloader`，输入为已完成构建的固件目录，不需要完整系统包。入口先完成主机校验及 UUU -dry，再确认目标并 RAM 启动 loader；仅写 boot0 从 0x400 开始的产品镜像及启动配置，不写 user area。写前/写后比较完整 user area 和 boot0 非镜像范围，镜像和 EXT_CSD 启动配置另行读回。独立部署不迁移旧 Linux 分区布局，新固件的 p1 extlinux 自动启动可能停在控制台；软件测试不等于实板冷启动验收。

### 6.2 完整系统的烧录流程

本工程已选择自制主机集成脚本：主机先生成整盘 AOSP Sparse 镜像，脚本随后完成 RAM boot → fastboot 写入系统镜像 → 写入 eMMC bootloader → 配置 eMMC 启动。协议执行为 `uuu task.uuu`，替代此前计划接入的 `uuu -b emmc_all`。开发者调用 [04 uboot/flash.py](../../sdk/bsp_imx/04-br-rtfs-integration/uboot/flash.py)，由它生成本次脚本、预检、确认及固定 USB 路径；具体命令见 [uboot/FLASHING.md](../../sdk/bsp_imx/04-br-rtfs-integration/uboot/FLASHING.md)。

用户已确认采用独立 FAT32 启动分区和 ext4 根分区。新镜像按以下布局组织，供整机烧录和组件更新共用：

| 区域 | 内容 | 更新方式 |
|---|---|---|
| eMMC boot0，从 `0x400` 字节开始 | 产品 U-Boot `.imx` | `bootloader` 目标写入 |
| user area 分区表 | p1、p2 的起点与容量 | 整盘烧录时写入 |
| p1，FAT32 启动分区 | `zImage`、`imx6ull-100ask-pro.dtb`、`extlinux/extlinux.conf` | kernel、DTB 按文件替换 |
| p2，ext4 根分区 | Buildroot rootfs | 独立分区 Sparse 写入 |

Linux 将 p1 挂载到 `/boot`；启动配置按 p1 内的路径引用 `/zImage` 和 `/imx6ull-100ask-pro.dtb`，root 参数指向 p2。这样，单独替换 rootfs 时，kernel、DTB 和启动配置保留在 p1。分区起点与容量由 04 的 `uboot/layout.json` 固定（当前 p1：LBA 2048、128 MiB；p2：LBA 264192、2 GiB），下载包保存同一份布局信息，供预检和组件更新使用。现有 03 镜像将启动文件放在 p2 的 `/boot` 下，新基线的整盘烧录负责建立上述布局。

1. **准备板端能力。**将 02 的现有 U-Boot 输入迁入 `04-br-rtfs-integration/uboot/`，作为新基线的唯一维护位置；在此补齐目标映射、两条自动启动路径、FAT 读写和启动配置加载能力。02 保留既有里程碑，04 集成新固件与主机烧录入口。
2. **制作下载包。**由 Buildroot 构建根文件系统，再由 genimage 组装 raw 整盘镜像，并将它转换成 Sparse。包内保存 loader、产品 U-Boot、系统镜像、布局及 SHA-256 清单；同时输出独立 zImage、DTB 和 rootfs 分区镜像。实际 task.uuu 由 flash.py 按操作和镜像有效块生成，保存在本次证据目录，不执行包内的任意脚本。
3. **执行主机预检。**`--dry-run` 检查校验和、镜像布局、逻辑容量、写入范围和 Sparse 块记录，再调用 UUU `-dry`。
4. **确认并烧录。**正式入口先重新预检，展示目标板和写入区域，再由开发者确认。脚本用 USB 路径指定板卡，启动 UUU，并持续显示和保存运行日志。
5. **验证结果。**检查各阶段是否完成，读回 boot0 中的产品 U-Boot、分区表和系统有效数据，再将板卡切回 eMMC 启动模式并断电启动。DONT_CARE 区域保留原内容，因此写后校验覆盖实际写入的数据范围。

### 6.3 预制 Sparse 的脚本方案

完整系统脚本依次完成 ROM 下载、系统镜像写入、U-Boot 写入和启动配置。以下片段展示命令顺序；`loader.imx` 在 RAM 中负责烧录，`product.imx` 是写入 boot0 的产品固件，两者可绑定同一个构建产物。04 入口会加入版本声明、板端只读 guard、SHA-256 读回和启动配置读回；下方仅展示协议主干，不能绕过正式入口直接作为交付脚本执行：

```text
SDP: dcd -f loader.imx
SDP: write -f loader.imx -ivt 0
SDP: jump -f loader.imx -ivt 0
FB: ucmd mmc dev 1 0
FB: flash all system.sparse.img
FB: flash bootloader product.imx
FB: ucmd mmc partconf 1 1 1 0
FB: Done
```

这里先将系统镜像写入 user area，再将 U-Boot 写入 boot0，最后设置启动确认信号和启动区域。`Done` 标记主机任务结束，板端后续的退出 fastboot 或重启步骤由烧录方案安排。

### 6.4 kernel、DTB、rootfs 独立更新

主机入口提供整机、kernel、DTB、rootfs 四种操作。每种操作都从 USB 下载模式启动同一新基线 loader，复用预检、确认、日志和写后验证流程。组件更新先核对板卡现有分区布局与下载包的布局一致，再执行对应写入。

| 操作 | 输入与写入范围 | 保留内容 |
|---|---|---|
| kernel | 原格式 zImage，替换 p1 中的 `zImage` 及必要 FAT 元数据 | DTB、启动配置、p2、分区表和 boot0 |
| DTB | 板级 DTB，替换 p1 中的 `imx6ull-100ask-pro.dtb` 及必要 FAT 元数据 | kernel、启动配置、p2、分区表和 boot0 |
| rootfs（rtfs） | p2 的独立 Sparse 镜像，写入 `rootfs` 目标 | 整个 p1、分区表和 boot0 |

kernel 和 DTB 先用 `FB: download` 送入 RAM，再通过 `FB: ucmd fatwrite` 写入指定文件。04 新基线已启用 `CONFIG_CMD_FAT` 和 `CONFIG_FAT_WRITE`。本地 U-Boot 在下载完成后将实际长度写入 `${filesize}`；fastboot 缓冲区固定为 `0x82000000`。kernel 更新的核心步骤如下，DTB 更新使用同一路径更换输入和文件名：

```text
FB: ucmd mmc dev 1 0
FB: download -f zImage
FB: ucmd fatwrite mmc 1:1 0x82000000 zImage ${filesize}
```

这种下载后写文件的方式也见于 [NXP FAT 写入脚本](https://github.com/nxp-imx/mfgtools/blob/uuu_1.5.21/uuu/fat_write.lst)。单个文件须满足第 5.1 节的 RAM 缓冲区限制，并在写入前检查 p1 空间；写后重新读取文件，核验长度和内容，同时检查其他启动文件保持原内容。

rootfs 使用独立 p2 镜像，其 Sparse 偏移从 p2 起点计算。主机核对展开长度与 p2 容量后执行：

```text
FB: flash rootfs rootfs.sparse.img
```

kernel 与 DTB 保持各自的原文件格式，整盘和 rootfs 分区镜像使用 AOSP Sparse。rootfs 写后核验有效块，并确认 p1、分区表和 boot0 保持原内容。三种独立更新均以重新启动预期系统作为验收出口。

### 6.5 既有里程碑入口（02/03）

| 入口 | 用途及 fastboot 的进入方式 |
|---|---|
| [uboot.py](../../sdk/bsp_imx/02-uboot-porting/uboot.py) | `ram` 下载后进入串口控制台；`emmc` 等待新 U-Boot 提示符，再由主机发送 `fastboot usb 0`；`console` 连接现有串口 |
| [deploy.sh](../../sdk/bsp_imx/03-kernel-busybox/deploy.sh) | 写入 1 GiB 的 p2 分区镜像；开发者先在板端执行 `fastboot usb 0`，再回主机确认烧录 |

两个入口的预检命令如下：

```sh
cd /home/pi/ea-emb-linux
sdk/bsp_imx/02-uboot-porting/uboot.py ram --dry-run
sdk/bsp_imx/02-uboot-porting/uboot.py emmc --dry-run
sdk/bsp_imx/03-kernel-busybox/deploy.sh --dry-run
```

uboot.py 的 emmc 流程按原启动选择写入 loader，并读回比较；deploy.sh 只覆盖 user area 中的 p2。uboot.py 的现有入口在预检后直接执行，deploy.sh 在预检后等待开发者按 Enter 确认。整机方案的新入口按前述“预检、确认、写入、验证”流程设计。镜像制作和 Linux 启动方法由各工作区维护。

本次查询、源码核对及历史记录索引：`artifacts/2026-10-09-uuu-usage-audit/collection.json`。04 软件实施与主机测试索引：`sdk/bsp_imx/04-br-rtfs-integration/uboot/artifacts/r2-host-audit/collection.json`；独立固件部署及迁移后测试索引：`sdk/bsp_imx/04-br-rtfs-integration/uboot/artifacts/bootloader-host-audit/collection.json`。R2 尚缺实际产品固件、真实 BR 输入及本板冷启动/写入证据。
