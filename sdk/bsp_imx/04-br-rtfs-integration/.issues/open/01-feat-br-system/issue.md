# 01 · 移植完整 Buildroot 开发板系统

建立日期：2026-10-09。状态：issue 保持 open。BR 系统需求沿用已确认基线；R2 的通用 U-Boot 基础层已按用户最新确认独立开章，采用 MBR/ext4、外部描述与产品 U-Boot target hash 门控，尚待细化和实现。既有原型及证据边界见 [progress.md](progress.md)。软件渲染、SSH 认证、PTY 语义、BR 官方依赖基线、IVI 分屏及自制主机烧录路线沿用已确认需求。

工作区：`/home/pi/ea-emb-linux/sdk/bsp_imx/04-br-rtfs-integration/`。本文件是 BR 系统需求与验收的来源；U-Boot 基础层的详细需求与验收由 [02 专章](../02-feat-uboot-foundation/issue.md) 单独维护，本系统作为其消费者。技术选择见 [adr.md](adr.md)，实施顺序见 [route.md](route.md)。

## 原始需求（烧录条目原文见集中笔记）

> 下一里程碑 workspace /home/pi/ea-emb-linux/sdk/bsp_imx/04-br-rtfs-integration/
> 继续使用issue-driven 对齐目标：移植完整的br开发板系统
> 2. usb_otg （应该是这个吧，就是 usb boot 使用的那个端口 ），启用 CDC_ECM. 让host 做dhcp server ,给嵌入式板卡分配静态ip ， 然后host 共享wlan网卡给这个设备，使得嵌入式板卡获得外网能力。
> 3. target 启用 sshd ，无密钥，root@imx。
> 4. systemd-udev 管理。
> 5. 图形栈：vendor 好像制作了fb , 转移到drm ， weston 合成器 , lib openGL ES, lib QT6 ，wayland QPA.
> 6. 做到br集成rsut package 和 rust 使用 br sdk sysroot做用户空间开发两条基线，使用前者来整合 rs-coreutils,使用后者作为日常开发基线。
> 7. 在br sdk上，做用户空间开发，使用QT bridge ，rs biding，前端纯qml，后端纯rs 开发com.wt,在gui只读展示shell 输出，风格Cappuccino mocha,提供 cli `wt list` `wt id <xx> -- <cmd>` 来在ssh pty 透传指令给指定id 的wt； 提供 `wt create` cli 和sdk接口创建实例。配置weston双wt 实例分屏。左屏跑fastfetch , 右屏跑userlog, 提供cli / sdk 接口 传递用户日志。两个cli 应用都用rust 做个基本原型。在做一个服务侦听触屏事件，转发event到userlog
> 8. 本轮先不配置wlan/hci 固件，主要验证范围是usb_ecm 和 图形栈

[UUU 用法与主机烧录方案](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

本次修订：用户选择自制主机集成脚本，将基础 U-Boot 迁入 04 维护，并增加 kernel、DTB、rtfs 的独立替换能力。此要求更新下列 S1、S2 及对应验收条件；其他系统与应用目标沿用已确认路线。

## 目标 spec

交付可复现的 Buildroot 系统和匹配 SDK，使 100ask i.MX6ULL Pro 从 eMMC 冷启动进入 systemd，通过 USB ECM 联网及 SSH 访问，在 LCD 上运行 Weston 和两个 com.wt 实例。系统集成、SDK 开发和整盘下载具有固定版本、明确入口和可核验产物。

| 编号 | 目标行为 |
|---|---|
| S1 | 消费独立通用 UUU/U-Boot 基础层，支持 USB 下载和 eMMC 正常启动。开发者设置 USB 下载模式后，一个主机入口完成 RAM loader、自动下载服务、整盘系统部署、产品 U-Boot 更新及必要启动设置；产品 target hash 一致时跳过镜像擦写。eMMC 冷启动自动引导本产品。仅适配当前板卡，基础层不内嵌 BR/BusyBox 项目约束；详细规则见 02 专章。 |
| S2 | 本项目提供 MBR/ext4 布局及外部启动描述，由通用工具合成含 kernel、DTB、rtfs 的单份整盘 Sparse。基础层同时支持不依赖完整项目包的独立板卡组件更新，以及对已有 Sparse 局部替换组件并输出新镜像；保留未选内容和稀疏写入语义。文件路径、分区几何及操作接口不得按本项目固化；详细规则见 02 专章。 |
| S3 | Linux 使用 ROM USB 下载所在物理端口提供 CDC ECM；host 为 DHCP server，以固定 MAC 保留租约给板端固定 IPv4 地址，并提供网关、DNS 和经主机 WLAN 的 NAT。板端由 DHCP 获得这些参数，USB 重连后仍获得同一地址。 |
| S4 | target hostname 为 `imx`；启用 OpenSSH sshd。用户确认 root 空密码，客户端不需登录密钥或输入密码。服务端 SSH host key 首次启动生成并持久化。host 提供 `imx` 名称解析，使 `ssh root@imx` 可用。 |
| S5 | systemd 为 PID 1，systemd-udevd 管理设备，systemd 管理 ECM、网络、sshd、Weston、wt 和触摸日志服务的生命周期；图形和输入不依赖固定 `/dev/input/eventN` 编号。 |
| S6 | 沿用目标内核的 DRM/KMS `mxsfb` 路线，驱动已连接的 1024×600 LCD。用户确认 Mesa 软件 GLES 提供库，Weston DRM/Pixman 合成，Qt6 Wayland QPA 与 Qt Quick software 渲染。验证 EGL/GLES 库及最小软件 GLES 示例，com.wt 不依赖 GPU。 |
| S7 | BR package 路线构建并安装 Rust coreutils；日常开发路线使用导出的 BR SDK、同一 ARM ABI、sysroot 和固定 Rust target 开发独立 Cargo 工程。用户确认采用 BR 官方 tag `2026.08` 及其依赖基线（Rust `1.97.1`、Qt `6.11.1`、Weston `15.0.1`），并锁定兼容的 coreutils 与 Qt Bridge for Rust 及其依赖。 |
| S8 | com.wt 的界面用 QML，业务后端、CLI 和 SDK 用 Rust；使用 Qt Bridge for Rust，CXX 绑定及生成胶水对日常开发透明。GUI 只读展示 shell/PTY 输出。主题暂按 Catppuccin Mocha 理解；若用户指另一套配色，在视觉实施前修正。 |
| S9 | wt 管理实例与命令生命周期，`wt list` 查询实例，`wt create` 和 Rust SDK 创建脱离调用端会话的实例，`wt id <xx> -- <cmd> [args...]` 指定实例执行命令。busy 时拒绝新命令，输出及完成 result 回显给调用端 PTY。实例通过独立会话与板端持有的内部 PTY，将生命周期与调用端 SSH PTY 解耦；SSH 断开后继续运行，GUI 订阅实例输出。 |
| S10 | 开机 launch 两个独立 wt GUI 实例并载入命令，由 Weston IVI-shell 固定到 LCD 左右 panel；左侧运行 Rust fastfetch 原型，右侧运行 Rust userlog 原型。GUI 到 panel 的 attach 与窗口交互归属后续独立开发的 shell，本轮交付固定开机布局。提供 userlog CLI 和 Rust SDK 发送日志。触摸服务监听 GT911 事件并转发给 userlog，Weston 继续正常接收触摸输入。 |

“完整系统”包含以上系统服务、工具链与应用原型。fastfetch 指 Rust 信息展示原型，不要求复刻上游全部功能；coreutils 指 uutils/coreutils 集成，具体版本、安装命令集合及必要系统命令的提供者在 ADR-05 固化。GUI 输出首轮覆盖普通文本、UTF-8、常见 SGR 颜色、换行与回车；是否扩展完整终端模拟须另行讨论，不据此声称支持任意 TUI。

## 验收条件

| 编号 | 完成判据 |
|---|---|
| A1 构建与启动 | BR external tree、固定版本与 hash、配置、overlay、patch、镜像布局和 SDK 入口可重建；构建路径遵循 ADR-01 的工作区内目录约定。耗时构建交由开发者执行，默认 `-j12`。eMMC 冷启动无需手输引导命令，进入本轮 kernel/DTB/rootfs，PID 1 为 systemd。 |
| A2 下载入口 | 板卡处于 USB 下载模式时，一个主机入口完成 loader、整盘部署、产品 U-Boot 的 hash 门控更新与启动设置，无需手动输入下载服务命令。dry-run、正式预检、目标确认及读回通过，产品镜像一致时证明没有重复擦写；完成独立 eMMC 冷启动。基础层细项按 02 专章验收，本系统另验证 BR 正常启动。 |
| A3 整盘与组件更新 | 整盘 Sparse 的有效块、跳过范围、实际传输量和耗时可核验。分别以独立输入更新板卡 kernel/DTB/rtfs，并对已有 Sparse 局部替换三类组件，验证指定内容、未选内容、必要 ext4 元数据和实际写入范围；原镜像不覆盖。独立板卡更新保留 MBR、bootloader 和启动配置，各自能启动预期系统。详细保留与验证规则由 02 专章维护。 |
| A4 ECM 网络 | 同一 USB 下载口在 Linux 下枚举 ECM；固定地址、host 名称解析、路由和 DNS 均可用。板端访问一个 HTTPS 外网站点，USB 拔插后恢复，主机 WLAN 联网保持正常；未配置板端无线固件。 |
| A5 SSH/服务 | `ssh root@imx` 无客户端密钥及密码输入，能执行命令并申请交互 PTY；host key 重启后不变化。udevd 和必要 systemd unit 状态正常，服务失败可定位。 |
| A6 图形 | DRM connector/mode、背光、Weston DRM/Pixman 和 Qt Wayland/software 实际运行身份明确。LCD 上文字、颜色与更新可见；软件 GLES 示例通过。两个 GUI 进程在左右半屏稳定展示，单个进程重启不改变另一个位置。 |
| A7 Rust 双基线 | 从 BR 构建产物调用已安装 coreutils，核验集成命令；导出并迁移 SDK 后，独立 Cargo 工程及 Qt Bridge for Rust 示例使用该 sysroot 构建，在板端执行。ELF、动态加载器、ARM hard-float ABI 和运行库与系统匹配，无主机 Qt/库路径混入。 |
| A8 wt | list/create/指定 ID 执行、SDK 创建调用均通过；两个实例 ID 独立，输出无串线；busy 拒绝新命令，不存在 ID、创建失败、子进程退出和非零返回有明确结果。输出与完成 result 回显调用端 PTY，CLI 返回命令退出状态。创建后关闭调用端 SSH PTY，实例及运行中的命令仍存活，GUI 可继续订阅；SSH PTY 输入、Ctrl-C、独立会话及断连行为按 ADR-06 验证。 |
| A9 原型与触摸 | Rust fastfetch 显示真实系统信息；userlog CLI/SDK 写入右侧，时间、来源和日志内容可辨识；触摸事件形成日志且不独占输入设备，坐标与屏幕对应。持续输出时验证有界内存及 GUI 响应。 |
| A10 交付 | 构建、部署、host 网络启停、SDK 开发、CLI/API 方法各有明确入口；运行证据归档至 `artifacts/`，正文仅引用证据索引。所有必需条目通过后归档 issue 并编写 close.md。 |

## 范围与状态边界

本轮优先实测 USB ECM 与图形栈，整盘下载、SSH、Rust SDK、wt 与触摸日志是这两条链路的交付组成部分。暂不配置 target WLAN/HCI 固件，不扩大到 HDMI、无线或其他外设验收。

02 的 U-Boot 已有既往启动基础；03 已按用户确认的实物烧录及板上 shell 结果关闭，范围见 [03 close.md](../../../../03-kernel-busybox/.issues/closed/01-feat-kernel-busybox/close.md)。DRM、ECM 及本里程碑的系统服务由 04 独立验收。

本轮先对齐并形成实施输入。代理不执行硬件写操作。硬件下载与写入按集中笔记的交付规则执行；主机联网脚本也应展示具体接口、地址、DHCP/NAT 变更再应用。
