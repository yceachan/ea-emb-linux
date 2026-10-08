# 01 · 移植 Kernel、BusyBox 并启动 eMMC shell

状态：已关闭（2026-10-09）。用户确认实物烧录及板上 shell 完成，并要求关闭本工作区。最终交付范围与验收依据见 [close.md](close.md)。建立日期：2026-10-07。

## 原始需求

> 已完成 uboot 移植工作，验证 emmc 烧录 uboot，并引导 kernel 4.9 vendor sys。
> 下一里程碑目标：移植 kernel，启动 busybox，完成开发板全外设 dtb 编译 + ddr、emmc、uart 最小外设与 busybox rtfs 的串口 shell 验证，在 fs 里配置 /boot，将 busybox 配置为默认启动引导项。
> workspace bsp_imx/03-kernel-busybox。在此 cwd 下用 issue-driven 方式讨论 adr、route。

实际工作区：`sdk/bsp_imx/03-kernel-busybox/`。

## 已有基础

上一阶段交付说明见 [U-Boot 状态](../../../../02-uboot-porting/STATUS.md)。用户已确认 eMMC 烧录、上电运行 U-Boot 和 vendor Linux 4.9 系统引导完成。

现有配置使用 UART1，U-Boot 为 1500000 baud，vendor Linux 为 115200 baud；DDR 地址为 `0x80000000`，容量 512 MiB。eMMC 接在 USDHC2，U-Boot MMC 编号为 1，U-Boot 从 boot0 启动，现有 vendor rootfs 位于 user area 的 DOS 第 2 分区。

现有 U-Boot 使用 `CONFIG_ENV_IS_NOWHERE=y`、`CONFIG_BOOTDELAY=-1`，关闭默认 `bootcmd` 与 Boot Standard。默认自动引导需要增加 U-Boot 启动入口，无法仅靠 rootfs 中的配置完成。

本地候选输入为 `sdk/vendor_mainline/linux-7.2.9/`、`busybox-1.36.1/` 和 `profile/prebuilt.env`。vendor 板级 DTS 位于 `sdk/bsp_imx/100ask_dts/`，用作接线和旧系统配置参考。

## 最终目标 spec

交付一套可复现的板级移植输入，生成目标内核 `zImage`、本阶段板级 DTB 和 BusyBox rootfs。rootfs 内包含 `/boot` 的内核、DTB 和启动配置；从 eMMC 加载目标内核并进入 BusyBox UART1 shell。默认自动引导由 04 的新 U-Boot 基线承接。

原“全外设 DTB”的目标含义是：以板卡实际资源为清单，逐项适配目标内核的节点、绑定、pinctrl、供电、复位及依赖，并完成本板 DTB 编译。节点状态、驱动支持情况与验证状态分别记录。编译通过不能代替绑定审查或硬件验收。无法适配的外设必须先对齐处置，不能用删节点、全部禁用或沿用无效属性来声称完成全外设移植。

用户已确认：实板验收限定为 DDR、eMMC、UART1 和 BusyBox rootfs；其余外设功能测试留待后续里程碑。2026-10-07 根据目标驱动限制与图纸新增资源，进一步确认本阶段完成全板资源清单、已有主线支持外设的描述与编译；HDMI 启用、AP3216C 驱动/绑定及无线功能支持留后续。延后项须明确记录接线、资料差异与驱动/固件缺口，不将它们标为适配完成。

用户确认板上已连接 1024×600 屏；本轮实板取证确认控制器为 GT911 电容触摸，基本触摸事件上报有效。vendor 的片内 TSC 存在实际引脚冲突并未成功 probe，主线适配按 GT911 的真实通路进行。

目标内核沿用工程现有 Linux 7.2.9。部署时直接替换 vendor rootfs，不执行备份；用户网盘中已有出厂镜像作为恢复来源。出厂镜像的具体文件及恢复过程本轮未检查，不将其写成已验证的恢复结果。

DDR 项目承接已经可启动的 ROM DCD/U-Boot 初始化，验证 Linux 的内存描述和基本读写稳定性。当前目标不包含重新设计 DDR 初始化参数，也不将基本测试解释为完整 DDR 压力、温度或长期可靠性认证。

## 验收条件与关闭边界

| 项目 | 完成判据 |
|---|---|
| 构建输入 | 固定源码提交、内核配置、BusyBox 配置、板级修改和 rootfs 文件；交付开发者执行的构建命令流及产物校验清单 |
| 板级资源与 DTB | 全板资源清单完整；本阶段已有主线支持外设逐项对应到目标 DTS；HDMI/AP3216C/无线延后项明确列出；绑定差异、冲突和驱动缺口均有处置；本板 DTB 编译成功，相关告警已审查 |
| Kernel | 启动日志和 `uname` 确认运行选定内核；传入本阶段 DTB，进入本阶段 rootfs |
| DDR | Linux 识别的物理内存与 512 MiB 地址范围及明确保留区一致；在不覆盖保留区的测试中未出现数据不一致或内核内存错误；测试范围随证据记录 |
| eMMC | 目标内核识别 USDHC2 上的 eMMC，挂载预定 ext4 rootfs；专用测试文件写入、同步、重启后读回校验一致 |
| UART1 | 启动到 shell 的串口读写连续可用，速率与启动配置一致；能够执行命令并获取输出 |
| BusyBox | `/sbin/init` 运行 BusyBox init；初始化 proc、sysfs、devtmpfs 等必要挂载；串口 shell 可用，退出后可重新进入 |
| rootfs 交付 | 静态 BusyBox 的 ARM ELF、applet 清单、启动文件与权限可核验；文件树归档保留 root 所有者、符号链接及执行权限；首轮覆盖启动、文件操作与板级诊断 |
| `/boot` | 内核、DTB、extlinux 配置与实际部署一致；默认项指向 BusyBox 系统；root 分区身份明确 |
| 默认引导 | 移交 04 的新 U-Boot 基线实现及验收 |

本工作区按用户确认的“实物烧录并进入板上 shell”阶段交付关闭。上表保留原验收项目；专项测试的记录边界及自动引导移交见 [close.md](close.md)。

## 已确认边界与剩余调查

1. 采用现有本地 Linux 7.2.9 固定提交。
2. 全板资源记录与本阶段支持外设描述/编译；HDMI/AP3216C/无线功能明确延后；DDR、eMMC、UART 和 BusyBox shell 实测。
3. 不备份，直接替换 vendor rootfs；出厂镜像作为恢复来源。
4. 首轮 BusyBox 覆盖启动、文件操作与板级诊断，不加入手工网络配置或网络服务验收；UART1 直接进入 root shell，不设登录环节，退出后重新进入。

eMMC 分区身份与边界已完成调查，最终采用 p2 ext4 分区镜像部署。RAM rescue 已取消；自动启动固件移交 [04 issue](../../../../04-br-rtfs-integration/.issues/open/01-feat-br-system/issue.md)。

技术选择见 [adr.md](adr.md)，阶段执行条件见 [route.md](route.md)，板级输入和外设边界见 [PORTING.md](../../../PORTING.md)。本轮已形成板级 DTS、配置片段、注册 patch、构建命令入口与 extlinux 文件；SDK 耗时构建命令由开发者把关执行。
