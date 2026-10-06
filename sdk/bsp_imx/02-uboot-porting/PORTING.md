# 01 · U-Boot 移植代码设计

本移植在主线 U-Boot 上增加独立板型，复用 i.MX6ULL 的 SoC 支持、DDR 初始化配置和外设驱动。板级代码处理本板时钟与运行参数，设备树描述引脚和设备连接。主机脚本负责选择 RAM 调试或 eMMC 烧录流程。

本文件解释当前实现。操作命令见 [02 · 主机脚本](HOST_TOOL.md)和 [03 · 构建与系统启动](RAM_BOOT.md)。实板结果与验证边界见 [06 · 验收状态](STATUS.md)。

## 源码如何组成

构建输入由 [base-revision](base-revision)、[overlay/](overlay/)和 [register-board.patch](register-board.patch)组成。`base-revision` 固定上游提交，`overlay/` 添加本板文件，补丁修改上游已有文件。

| 文件 | 设计职责 |
|---|---|
| [overlay/board/100ask/imx6ull/Kconfig](overlay/board/100ask/imx6ull/Kconfig) | 选择板级目录、配置头文件和 ROM 镜像配置 |
| [overlay/board/100ask/imx6ull/Makefile](overlay/board/100ask/imx6ull/Makefile) | 将本板 `imx6ull.c` 编入 U-Boot |
| [overlay/board/100ask/imx6ull/imx6ull.c](overlay/board/100ask/imx6ull/imx6ull.c) | UART 时钟、DDR 容量、启动参数地址和板名 |
| [overlay/arch/arm/dts/imx6ull-100ask-pro.dts](overlay/arch/arm/dts/imx6ull-100ask-pro.dts) | 本板内存、引脚和外设连接 |
| [overlay/arch/arm/dts/imx6ull-100ask-pro-u-boot.dtsi](overlay/arch/arm/dts/imx6ull-100ask-pro-u-boot.dtsi) | U-Boot 早期设备模型所需的节点 |
| [overlay/configs/100ask_imx6ull_ram_defconfig](overlay/configs/100ask_imx6ull_ram_defconfig) | 启用本轮启动和维护所需的功能 |
| [overlay/include/configs/100ask_imx6ull.h](overlay/include/configs/100ask_imx6ull.h) | 板级常量和默认环境 |
| [register-board.patch](register-board.patch) | 板型注册和串口分频修正 |

补丁向 `arch/arm/mach-imx/mx6/Kconfig` 添加 `TARGET_100ASK_IMX6ULL`，并引入本板 Kconfig。新板型依赖 `MX6ULL`，选择设备模型、温度设备模型和低功耗 IOMUX 支持。设备模型是 U-Boot 管理驱动与设备的框架。

本板 Kconfig 将 `SYS_VENDOR` 设为 `100ask`，将 `SYS_BOARD` 设为 `imx6ull`。因此编译入口是 `board/100ask/imx6ull/`。`SYS_CONFIG_NAME=100ask_imx6ull` 选择对应配置头文件，`CONFIG_DEFAULT_DEVICE_TREE` 选择本板设备树。

## ROM 镜像与 DDR 初始化

当前方案由 Boot ROM 直接加载完整 U-Boot，没有独立 SPL 阶段。SPL 是先于完整 U-Boot 运行的小型引导程序。交付镜像为带 ROM 头的 `u-boot-dtb.imx`，入口地址由 `CONFIG_TEXT_BASE=0x87800000` 设置。

ROM 头包含入口信息和 DCD。DCD 是 ROM 执行的寄存器初始化表。它在 U-Boot 运行前配置时钟、DDR 引脚和内存控制器，使 ROM 可以将 U-Boot 放入 DDR。

本板通过 `IMX_CONFIG` 复用上游 [board/nxp/mx6ullevk/imximage.cfg](../../vendor_mainline/uboot-2026.07/board/nxp/mx6ullevk/imximage.cfg)，没有另建 DDR 初始化实现。RAM 下载脚本先执行 DCD，再写入镜像并跳转。eMMC 启动时由 ROM 处理镜像头与 DCD。

这份上游配置使用 `BOOT_FROM sd` 生成 SD/MMC 的 ROM 镜像格式。实际 eMMC 启动区域仍由板卡启动配置和 eMMC 启动分区选择决定。它不要求另外构建一份 eMMC 专用 U-Boot。

进入 U-Boot 后，`dram_init()` 调用 `imx_ddr_size()`，将检测到的容量写入 `gd->ram_size`。这一步读取已初始化的 DDR 配置，不替代 DCD，也不重新训练 DDR。设备树和配置头文件描述的目标容量均为 512 MiB。

复用上游 DCD 是当前实现的硬件前提。系统启动和局部内存测试的结果由 STATUS.md 记录，不能据此推断完整 DDR 时序、温度范围和稳定性均已验收。

## 板级初始化与 UART

[imx6ull.c](overlay/board/100ask/imx6ull/imx6ull.c)保留四个板级入口。

```c

int board_early_init_f(void)
{
	struct mxc_ccm_reg *ccm = (struct mxc_ccm_reg *)CCM_BASE_ADDR;

	/* ROM SDP enables PLL3. Select PLL3 / 6, then UART_PODF / 1. */
	clrbits_le32(&ccm->cscdr1, MXC_CCM_CSCDR1_UART_CLK_SEL |
		     MXC_CCM_CSCDR1_UART_CLK_PODF_MASK);
	if (imx_get_uartclk() != 80000000)
		return -EINVAL;

	return 0;
}

int dram_init(void)
{
	gd->ram_size = imx_ddr_size();
	return 0;
}

int board_init(void)
{
	gd->bd->bi_boot_params = PHYS_SDRAM + 0x100;
	return 0;
}

int checkboard(void)
{
	puts("Board: 100ask i.MX6ULL Pro (UART1 / eMMC)\n");
	return 0;
}

```

| 入口 | 行为 |
|---|---|
| `board_early_init_f()` | 选择 UART 时钟源和分频，要求输入时钟为 80 MHz |
| `dram_init()` | 从内存控制器配置读取 DDR 容量 |
| `board_init()` | 将 ARM 启动参数地址设为 DDR 基址加 `0x100` |
| `checkboard()` | 输出本板名称与控制台、存储说明 |

`board_early_init_f()` 清除 `CSCDR1` 的 UART 时钟源选择位和分频位。当前选择是 PLL3 除以 6，再除以 1，得到 80 MHz。函数随后调用 `imx_get_uartclk()` 检查结果，若不是 80 MHz，返回 `-EINVAL`。这里保留明确的硬件前提，不用另一波特率掩盖时钟错误。

默认串口是 UART1，目标波特率为 1500000。配置头文件还允许切换到 115200，供现有 vendor Linux 使用。引脚连接和 `stdout-path` 由设备树维护，波特率寄存器由共享 MXC 驱动设置。

补丁修改 `drivers/serial/serial_mxc.c` 的 `_mxc_serial_setbrg()`。驱动使用分子和分母设置 UART 速率，UBIR 与 UBMR 保存的值均比实际分子、分母小 1。当前驱动的 `RFDIV` 宏值为 4，硬件编码对应实际除以 2。波特率关系是：

```text
baudrate = (UART 输入时钟 / 2 / 16) × (UBIR + 1) / (UBMR + 1)
```

补丁用 `rational_best_approximation()` 求 `16 × baudrate` 与 `clk / 2` 的比例，并将结果减 1 后写入寄存器。在 80 MHz、1500000 baud 下，比例为 `3/5`，因此 UBIR=2、UBMR=4。`CONFIG_LIB_RATIONAL=y` 为驱动提供该函数。

这项修改位于共享驱动，会影响生成源码快照中的 MXC UART 实例。`build.sh` 在独立快照中应用补丁，上游源码仓库保持原内容。补丁文件的职责包含驱动修正，不能仅按它的文件名理解为板型注册。

## 设备树中的硬件连接

[本板 DTS](overlay/arch/arm/dts/imx6ull-100ask-pro.dts)继承上游 `imx6ull.dtsi` 的控制器节点，再设置本板属性。它描述内存、UART1、USDHC2 和 USB OTG1。

| 节点 | 当前描述 | 设计作用 |
|---|---|---|
| `memory@80000000` | 起点 `0x80000000`，容量 `0x20000000` | 描述本板 512 MiB DDR |
| `chosen`、`uart1` | `serial0:1500000n8`，UART1 TX/RX 引脚 | 选择控制台和引脚复用 |
| `clks` | 声明 PLL3 PFD2 的目标频率为 320 MHz | 提供本板的时钟配置请求 |
| `usdhc1` | 禁用 | 只启用本板连接的 eMMC 控制器 |
| `usdhc2` | NAND 引脚组复用，8 位，最高 52 MHz，不可移除 | 描述 eMMC 连接与高速模式 |
| `usbotg1` | `dr_mode="peripheral"`，禁用过流检测 | 为 USB fastboot 提供设备模式接口 |
| `wdog1` | 启用节点 | 保留该设备的硬件描述，实际驱动行为仍由生成配置决定 |

USDHC2 保留 SoC 的 `mmc1` 别名。当前 MMC 驱动通过设备序号选择时钟，序号 1 对应 USDHC2。不能为了让唯一设备显示为 MMC 0，就直接重命名这个别名。相关实现见 [fsl_esdhc_imx.c](../../vendor_mainline/uboot-2026.07/drivers/mmc/fsl_esdhc_imx.c)。

eMMC 描述包含 `no-1-8-v`，不请求 1.8 V 切换。USB OTG1 使用外部主机供电的设备模式，没有配置本板向外提供 VBUS。设备树中的模式与 fastboot gadget 驱动配置共同决定 USB 行为。

[U-Boot 专用 DTSI](overlay/arch/arm/dts/imx6ull-100ask-pro-u-boot.dtsi)继承上游早期节点定义，并为 UART1 和它的引脚节点添加 `bootph-all`。该属性让节点在 U-Boot 各启动阶段可用，以支持早期控制台。

这份设备树供 U-Boot 自身驱动使用。启动现有 Linux 时，控制台命令另外加载 eMMC 中的 vendor DTB。U-Boot DTB 与 Linux DTB 分别维护各自运行环境的硬件描述。

## 功能配置与默认环境

[defconfig](overlay/configs/100ask_imx6ull_ram_defconfig)是功能选择入口。该配置生成的同一镜像用于 RAM 下载和 eMMC 启动。它启用 `bootz`、MMC、DOS 分区解析和 ext4 读取，用于加载现有 vendor 系统。`CONFIG_DOS_PARTITION` 解析分区表，ext4 驱动读取分区内文件，两者承担不同职责。

诊断功能包含设备模型查看、内存测试和 CRC32。内存测试的配置范围为 `0x90000000` 到 `0x91000000`。网络、烧写 fuse 和环境保存命令未启用，当前工作流集中在串口、eMMC 和 USB。

USB 配置启用 ChipIdea 设备控制器、fastboot gadget 和主线 MMC flash。`CONFIG_FASTBOOT_UUU_SUPPORT` 提供 UUU 执行控制台命令所需的 UCmd 支持。实际 fastboot 写入设备由 `CONFIG_FASTBOOT_FLASH_MMC_DEV=1` 固定。

默认环境由[配置头文件](overlay/include/configs/100ask_imx6ull.h)维护。`mmcdev=1` 指向本板 eMMC，`mmcpart=2` 指向 user area 内的 DOS 第 2 分区。这里的 `mmcpart` 环境变量与 raw partition 描述中的硬件分区编号不是同一个含义。

`CONFIG_ENV_IS_NOWHERE=y` 使环境仅在 RAM 中生效。`bootdelay=-1` 且没有默认 `bootcmd`，因此 RAM 下载和正常 eMMC 启动都停在控制台。当前代码没有根据 USB 启动来源自动进入 fastboot 的板级入口。

## RAM 地址与流程边界

当前实现复用 RAM 缓冲区，不把调试、烧录和 Linux 启动做成独立固件。地址来自配置、默认环境和操作脚本：

| 地址或范围 | 使用者 | 当前用途 |
|---|---|---|
| `0x80000000`，512 MiB | ROM、U-Boot、Linux | DDR 地址空间 |
| `0x80000100` | `board_init()` | ARM 启动参数地址，不是手工加载 DTB 的缓冲区 |
| `0x87800000` | ROM 镜像和链接配置 | U-Boot 入口及链接地址，运行后由通用代码重定位 |
| `0x82000000`，16 MiB | fastboot | 镜像下载缓冲区，手工启动时也可用于 zImage |
| `0x83000000` | 烧录脚本、Linux 启动命令 | 分别用于写后读回和加载 vendor DTB |

烧录结束后若要启动 Linux，按启动文档重新加载 zImage 和 DTB，镜像大小的构建检查与烧录 raw partition 的保留范围一致，具体写入区域由 04 号文档维护。

板端提供 fastboot 能力，主机决定何时启用它。`uboot.py ram` 下载后保留控制台，`uboot.py emmc` 下载后通过串口发送 fastboot 命令。这种分工保留 RAM 调试入口，也不需要板端猜测 USB 下载的操作意图。

`bootloader` 的地址映射在烧录脚本运行时设置，不是当前默认环境的一部分。官方内置脚本所需的环境适配与其他路线由 [05 · UUU 行为与适配](UUU_COMPAT.md)维护。

## 构建快照与维护入口

[build.sh](build.sh)从固定提交导出上游源码，覆盖本板文件，再应用补丁。它使用本板 defconfig 生成 `out/.config`，记录源码提交和移植输入校验清单。完整构建生成 ROM 镜像后，将交付文件复制到 `artifacts/`。

修改板级行为时，维护 `overlay/board/`。修改引脚和设备连接时，维护 `overlay/arch/arm/dts/`。修改功能或默认环境时，维护 defconfig 和配置头文件。共享驱动的差异维护在补丁中。

构建目录中的 `src/` 是一次输入快照，不是移植源码的维护位置。修改输入后，重新创建构建目录，避免继续编译旧快照。构建命令和工具链使用方法由 03 号文档维护，本文件不重复操作步骤。
