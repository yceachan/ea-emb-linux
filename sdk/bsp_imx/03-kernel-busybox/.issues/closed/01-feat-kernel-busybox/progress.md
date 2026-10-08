# 进度

## 2026-10-07 · R0 实板取证

需求已确认：Linux 7.2.9、全外设描述与编译、最小外设实测、直接替换 vendor rootfs且不备份。

已在 vendor Linux 4.9.88 中完成串口取证，确认 GT911 电容触摸及用户产生的触摸事件、片内 TSC 的真实引脚冲突、显示/触摸坐标声明差异，以及 eMMC rootfs 分区范围。实际硬件结论和技术处置由 ADR 维护。

取证索引：`artifacts/2026-10-07-154632-vendor-survey/collection.json`。运行 DTB 已完整取回，主机与板上 SHA-256 一致；串口记录、命令和反编译 DTS 已归档。

下一阶段：依据实板资料形成 Linux 7.2.9 的板级移植输入，继续讨论默认启动入口及 rootfs 部署方式。未执行主线构建、烧录或 vendor 系统配置修改。

## 2026-10-07 · R1 板级输入与路线收敛

已形成 `kernel/` 下的单板 DTS、配置片段、DTB/compatible 注册 patch 及源码快照构建入口；资源与迁移边界由 `PORTING.md` 维护。轻量 cpp/dtc 编译通过，无 dtc 告警；完整内核配置、构建和 schema 验证尚未执行。

用户确认 LCD 默认输出；HDMI 启用、AP3216C 与无线功能留后续。默认引导选择固定 eMMC 1:2 的 sysboot/extlinux、3 秒等待；rootfs 选择静态 BusyBox 和 RAM 救援文件树部署。extlinux 文件已准备；保留原 ext4 后清除旧内容、展开目标归档的实施提案见 ADR-03。

静态检查索引：`artifacts/2026-10-07-kernel-input-audit/collection.json`。

下一步：开发者审阅并运行 README 的本板配置/构建命令；落实 BusyBox/rootfs、救援包与安装脚本，核验下载大小和启动地址。未构建完整目标内核、未改动 U-Boot 输入、未烧录或修改实板文件系统。

## 2026-10-07 · R1 开发者构建完成，进入 BusyBox 集成讨论

用户报告 kernel 构建成功；主机复核确认本轮 zImage 与本板 DTB 已生成，产物校验清单通过，W=1 DTB 日志没有告警。内核已内建外部 gzip initramfs、MMC/ext4 和 UART 启动所需配置；这仍不代表实板启动或外设验收通过。

构建复核索引：`artifacts/2026-10-07-kernel-build-review/collection.json`。

当前讨论：同一静态 BusyBox 用于 eMMC 目标 rootfs 和 RAM 部署环境；救援包本体为独立外部 cpio.gz，运行时根目录在 RAM，携带待安装归档并离线替换 p2 文件树。具体 BusyBox applet、初始化文件与安装脚本尚待形成输入。

## 2026-10-07 · R2 设计目标对齐

用户确认首轮命令范围为启动、文件操作和板级诊断，不增加手工网络配置；UART1 直接进入 root shell，不设登录环节，退出后自动重启 shell。BusyBox 的复用方式、初始化职责、串口交互、故障路径、救援安装边界与交付顺序已整理到 ADR-06；相应验收条目进入 issue，先检查 RAM 启动再部署 eMMC 的顺序进入 route。

当前仅整理设计目标，未生成 BusyBox 配置、启动脚本或安装器，未执行构建或实板操作。

## 2026-10-07 · R2 集成输入交付

已实现固定 BusyBox 配置与 -j12 构建/安装入口，目标 rootfs 初始化及串口 shell，RAM `/init`，固定 p2 的预检/安装器和 tar/newc cpio 打包工具。正常与救援文件树复用同一 BusyBox，使用已校验的本轮 kernel/DTB。构建与应用说明统一见 `rootfs/README.md`。

配置解析通过；12 项隔离主机测试通过，覆盖归档格式、组装与安装边界。BusyBox find 删除错误可能返回零的问题已显式处理；串口 wrapper 在 init 重置 tty 后设置最终波特率与流控。

检查索引：`artifacts/2026-10-07-busybox-input-check/collection.json`。

尚未执行 ARM BusyBox 完整编译或生成真实部署包，未实际挂载、安装或启动板卡。下一步由开发者执行构建/打包命令，再核验救援包大小和 U-Boot/RAM 布局，形成实际加载命令。

## 2026-10-07 · 部署方向变更

用户取消 RAM rescue，要求删除相关文件；禁止代理烧录或继续采集硬件。rescue 源码、包体与专用部署入口已删除。当前交付改为 p2 ext4 镜像，制作方法由工作区 DEPLOY.md 维护。这会重建 p2 文件系统，原 ADR-03 的保留 ext4 文件树安装路线已撤销；镜像尚未制作，新方案未执行实板验收。

BusyBox 与 rootfs 源码输入已统一到 `rootfs/`，已有构建产物仍保留原路径以维护来源记录。

[UUU 用法与主机烧录方案](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## 2026-10-09 · 实物交付与关闭

用户确认实物烧录及板上 shell 完成，要求关闭 03。issue 已归档至 closed，最终交付范围见 [close.md](close.md)；自动引导移交 04，新 U-Boot 基线在 04 维护。

关闭索引：`artifacts/2026-10-09-close/collection.json`。
