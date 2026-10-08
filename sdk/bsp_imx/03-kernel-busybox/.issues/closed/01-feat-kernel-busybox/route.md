# 实施路线（已归档）

当前部署约束（2026-10-07）：用户已取消并删除 RAM rescue，代理不得操作板卡。BusyBox 与 rootfs 工作区统一到 `rootfs/`。直接烧录 p2 ext4 镜像的方案由 [DEPLOY.md](../../../DEPLOY.md) 维护，涉及重建 p2 文件系统；旧文中的 RAM rescue/文件树安装路线不再执行。用户已确认直接镜像实物烧录及板上 shell 完成，关闭范围见 [close.md](close.md)。

状态：2026-10-09 已关闭。目标镜像烧录和板上 shell 已由用户确认；早期 RAM rescue 步骤已取消，默认自动引导移交 04。最终范围见 [close.md](close.md)。

## R0 · 确认范围与部署条件

Linux 7.2.9、全板资源记录、本阶段支持外设描述与编译及最小外设实测的范围已确认。HDMI 启用、AP3216C 与无线功能已确认留后续。rootfs 直接替换 vendor，不备份，恢复来源为用户网盘的出厂镜像。启动入口已选 sysboot/extlinux 与 3 秒倒计时，rootfs 已选静态 BusyBox 和 RAM 救援文件树部署；继续核验地址与具体安装步骤。

交付开发者执行的只读板卡调查命令，获取 eMMC 分区起止、文件系统、容量/使用量、分区身份、现有 `/boot` 和 U-Boot 环境。结合结果确定 BusyBox rootfs 的目标位置和允许写入的范围。

阶段出口：ADR 有明确确认结果；替换目标、分区边界和容量已核实，保持现有分区表。

本轮已在 vendor 系统完成分区、DTB、触摸、pinmux 与驱动调查，R0 的实板资料已具备。以下只读命令保留为后续部署前复核入口；完整命令记录由取证目录维护：

```sh
uname -a
cat /proc/cmdline
cat /proc/partitions
cat /proc/mounts
df -h
cat /sys/class/block/mmcblk1p2/start
cat /sys/class/block/mmcblk1p2/size
fdisk -l /dev/mmcblk1
blkid /dev/mmcblk1p2
ls -l /boot
```

本轮未中断 vendor 系统返回 U-Boot。后续 U-Boot 侧已有可用的调查命令如下；`mmc dev 1 0` 只选择 user area，不写入存储：

```text
mmc list
mmc dev 1 0
mmc info
mmc part
printenv
```

Linux 侧调查已执行；U-Boot 侧命令留待后续部署阶段。MBR 零签名与启动参数的具体处置由 ADR-03 维护。

## R1 · 形成 Kernel 和 DTB 移植输入

固定目标源码提交，准备本板 DTS、注册修改和内核配置。当前候选见工作区 `kernel/` 与 `PORTING.md`。先确保 memory/UART1/USDHC2 及启动依赖完整，再逐项补齐本阶段支持外设描述。对引脚冲突、旧绑定和驱动缺口给出具体处置。

交付使用独立输出目录的配置与构建脚本、配置差异和 DT 检查命令。SDK 耗时构建由开发者执行；代理分析返回的日志并修正移植输入。检查以本板 DTB 为目标，不无故编译和验证所有板卡。

阶段出口：本轮 `zImage`、本板 DTB 与配置有对应来源；本阶段范围内未解决的阻碍已先与用户对齐。编译和静态审查结果不能标成实板通过。

## R2 · 形成 BusyBox rootfs 与 `/boot`

按 ADR-06 固化 BusyBox 配置、rootfs 文件布局、init/inittab/rcS 及必要挂载；交付静态 BusyBox 的构建和安装命令流，使用 `-j12`。检查 ARM ELF、静态链接、applet 链接和启动文件权限。首轮仅覆盖启动、文件操作与板级诊断。

按已选择路线生成 rootfs 文件树和归档，UID/GID 固定为 root，检查符号链接与执行权限。准备独立救援 initramfs，其中包含安装脚本和目标归档；目标 BusyBox 使用 init/inittab/rcS，救援使用 `/init`，两者复用同一静态二进制。保留原 ext4 的特性与 UUID，部署时不格式化。准备与本轮内核、DTB、分区身份匹配的 `/boot/extlinux/extlinux.conf`，默认标签为 BusyBox。

构建与应用入口见工作区 `rootfs/README.md`；完整编译与产物打包后核验静态 ARM ELF、实际下载大小及 RAM 地址布局。

阶段出口：开发者拿到可审阅的 rootfs 内容、校验清单与具体写入步骤；命令中没有未解析的设备/分区占位符。需要管理员权限的手工命令使用 `sudo`。

## R3 · 手工启动与最小外设实测

先仅加载本轮 kernel、DTB 与救援 initramfs 到 RAM，进入 BusyBox 串口环境。确认内核身份、RAM 根、PID 1、MMC 枚举、串口命令与控制终端，安装脚本此时不自动运行。此步骤是对已选部署环境的启动检查，不另建一套内核或板级描述。

原 RAM 救援部署路线已撤销，当前分区镜像制作与启动验收见工作区 DEPLOY.md。

[UUU 用法与主机烧录方案](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

使用现有 U-Boot 手工加载本轮 kernel/DTB，先验证目标 Linux 能挂载 BusyBox rootfs 并进入 UART shell。

核对内核身份、DT 身份、命令行、挂载和 PID 1；进行约定范围的 DDR 数据测试，以及 eMMC 专用文件写入、同步、重启读回校验；检查 shell 退出后的重新进入行为。

阶段出口：最终交付 DTB 下的 DDR/eMMC/UART/BusyBox 行为通过。若有故障，按串口交接、内核早期启动、MMC/root 挂载、init 启动定位；必要时讨论临时 initramfs，不直接改变最终落盘目标。

## R4 · 默认引导移交

自动引导由 [04 issue](../../../../04-br-rtfs-integration/.issues/open/01-feat-br-system/issue.md) 的新 U-Boot 基线实现。03 交付保留已有 U-Boot 的手工启动入口，方法见工作区 DEPLOY.md。

## R5 · 交付与关闭 issue

将产物、源码/配置身份、构建日志和串口验证记录归档至 `artifacts/`。更新交付文档，分别说明本阶段外设适配结果、延后项和已实测范围；未测试功能不标记通过。

用户确认实物烧录及板上 shell 完成后，issue 已移入 `.issues/closed/`，关闭依据、专项记录边界及后续归属见 [close.md](close.md)。
