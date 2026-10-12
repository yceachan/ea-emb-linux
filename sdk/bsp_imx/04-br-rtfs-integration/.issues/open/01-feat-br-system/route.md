# 实施路线

状态：2026-10-09 对齐阶段。阶段出口按 [issue.md](issue.md) 判定，选择及约束由 [adr.md](adr.md) 维护。

## R0 · 对齐与固定输入

完成已有源码、硬件描述和host网络审查，确认双进程布局路线；先完成可审阅的文档，不以计划表示实现完成。

出口：用户确认实质路线，未决问题有明确后续处理条件。代码实施建立隔离 worktree，输入归属按 ADR-01 执行。实施先推进 R2 的基础固件迁移与主机入口，再用 R1 的真实 BR 产物完成整机集成验收。

## R1 · BR 集成与 Rust 工具链

基于官方 tag `2026.08` 建立 BR2_EXTERNAL 及板级配置，固定源码快照/patch、glibc/C++ 工具链、systemd 与 kernel 输入；采用官方 Rust `1.97.1`、Qt `6.11.1` 与 Weston `15.0.1` 配方及 hash，锁定 external Cargo 依赖。形成 configure/build/sdk命令流，默认 `-j12`，交给开发者执行。轻量检查覆盖配置能否选中、hash、patch和实际依赖约束。

按 ADR-05 固定兼容的 Qt Bridge for Rust 发布版本，并验证 ARMv7 交叉构建入口。构建基础 systemd/网络/SSH 系统与 Rust hello-world，随后逐层加入 coreutils 及图形；这些阶段是同一配置的递进，不维护两套产品配置。构建失败按实际错误修正，不删掉必需包规避问题。

出口：可复现的基础 rootfs和匹配工具链，有真实大小与 ABI数据；官方工具链与 external 依赖锁已通过构建。

## R2 · 基础固件与整机、组件更新

按 [uuf/U-Boot 专章](../02-feat-uboot-foundation/issue.md) 和[独立实施路线](../02-feat-uboot-foundation/route.md) 推进固件能力、分立镜像一键部署与组件独立更新。基础层验证通过后，本 BR 项目作为外部消费者接入，其冷启动与 systemd 验收独立完成。

[UUU 用法与历史审查](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## R3 · ECM、host 联网与 SSH

配置 Linux单功能ECM和systemd-networkd，准备host专用DHCP/名称解析/NAT启停脚本。dry-run列出网段冲突、接口归属、固定租约和firewalld策略；不以dry-run代替实际网络验收。准备OpenSSH空密码认证及host key持久化。

由开发者验证物理USB口、Linux ECM枚举、固定租约、`root@imx`交互PTY、DNS/HTTPS和USB重连。失败优先按UDC/gadget、host驱动、DHCP、路由、DNS、SSH认证逐段定位。

出口：A4/A5通过；board联网只经USB，未引入target WLAN/HCI固件。

## R4 · DRM、Weston 与 Qt6 最小图形

先核验现有kernel/DTB的DRM connector/mode和GT911，再集成Mesa库、Weston/Pixman及Qt6 Wayland/software。先运行shm客户端与最小QML文字界面，再验证软件GLES库和示例；记录内存/CPU/刷新行为以确定本板可接受的图形负荷。

核对 Weston `15.0.1` 与 Qt `6.11.1` 的 IVI 接口，做两个独立 surface 的固定 panel 布局原型，并配置开机 launch 及默认命令载入。同步完成 SDK 导出/迁移与 Qt Bridge for Rust 最小工程，验证 CXX 生成胶水由构建入口封装；核对 host 生成工具与 target 链接来源。

出口：A6的基础图形及A7的SDK/Qt桥接路径通过。性能不符合目标时先对齐动画、输出速率或实现路线，再开发com.wt。

## R5 · com.wt、Rust 原型与触摸日志

实现 Rust SDK/Unix socket 服务、实例与内部 PTY 管理、CLI、只读 QML 输出和主题。按 ADR-06 实现独立会话、busy 拒绝新命令、向调用端 PTY 回显输出/result，以及调用端断连后继续运行；测试真实 PTY 控制行为、argv、退出状态与异常返回。复用 R4 的固定开机布局，载入 Rust fastfetch 和 userlog CLI/SDK；后续 shell 负责 GUI 到 panel 的 attach 与窗口交互。

最后接入不独占GT911的触摸日志服务，核验多点帧、坐标、丢失事件和udev生命周期。以持续日志验证缓存边界、GUI更新及两个实例隔离，不为未请求的完整终端模拟扩展范围。

出口：A8/A9及双进程分屏验收通过，实际接口与方法形成交付文档。

## R6 · 整机交付与关闭

核对最终系统的冷启动、USB重连、SSH与两窗口默认任务，以及独立SDK工程在该系统上的执行。只对本轮真实变更补必要验证，避免重复扩大回归。

最终交付说明按系统使用、构建/部署、SDK开发各自维护来源；运行证据只引用`artifacts/`索引。全部完成后移动到`.issues/closed/`并写close.md，列明每项完成依据和明确延后项。缺少开发者构建或实板证据时保持open。
