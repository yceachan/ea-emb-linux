# 技术决策

状态：2026-10-09 目标对齐，主机烧录路线已确认。每项明确区分用户已确认选择、实施建议和未验证条件；验收定义由 [issue.md](issue.md) 维护。

## ADR-01 · 基线、输入归属与工具链

已确认：Buildroot 使用官方 tag `2026.08`，本地与 GitHub 开发分支为 `yceachan/2026.08-dev`，依赖采用该 tag 的官方包版本与 hash。用户空间绑定使用 Qt Bridge for Rust。源码目录名称不作为版本证据，BR Makefile 实际声明为 `2026.08`。

| 输入 | 固定身份 |
|---|---|
| Buildroot | `sdk/vendor_mainline/buildroot-2025.02`，tag `2026.08`，`d5180309b1b66ef3b8eaccca70ad69be8e0729a1`；开发分支 `yceachan/2026.08-dev` |
| U-Boot 起点 | 02/base-revision：`a7a5989d4250fc080d5cb9777cd9323d8705786f`，板级输入迁入 04 后继续迭代 |
| Linux | 03/kernel/base-revision：`5fce161649b4d779d1b76d9fcd52dc77779774b8` |
| 图形包 | 官方 tag 配方：Qt `6.11.1`、Weston `15.0.1` |
| Rust 工具链 | 官方 tag rust-bin 配方：Rust/Cargo `1.97.1`，同版本 host/target rust-std |

04 建立 BR2_EXTERNAL，管理板级 defconfig、rootfs overlay、服务、镜像生成和 external packages。用户已确认将基础 U-Boot 迁入 04 维护：实施时在 `04-br-rtfs-integration/uboot/` 接管固定 revision、板级 overlay、patch 和构建入口，此后新基线只在这里修改。02 保留既有里程碑及迁移起点，04 构建使用迁入的固定输入。kernel 配置与 DT 继续由 03 维护，04 引用并集成。BR 源码和包更新采用固定快照及 patch，不在共享上游源码树直接修改。

建议 BR 自建 ARM Cortex-A7 hard-float/glibc/C++ 动态工具链，导出同一次系统构建的 SDK。glibc 是本地 systemd 包的约束；Qt6 需要 C++、线程、wchar 和动态库。迁入的 U-Boot 先沿用其已固定的 prebuilt 构建工具链，04 用户空间使用 BR SDK，不复用来源不明的 vendor sysroot。内核构建与 rootfs 的 ABI 边界按实际产物检查。

complex feat 的代码实施在 `~/worktrees/ea-emb-linux/<agent>/<branch>` 隔离 worktree 中进行；当前只在用户指定工作区建立对齐文档。

本 BR 项目的构建根仍约定放在 04 工作区的 `build/` 下，源码快照与输出分开；完整构建由开发者执行，默认 `-j12`。用户最新确认的通用 U-Boot 基础层不把这个项目约定作为接口硬条件：其 source/toolchain/work/input/output/log 路径由调用参数或环境提供，不依赖固定仓库路径或 CWD。04/build/uboot/ 仅可作为本仓库的示例或便利配置。详见 [02 专章](../02-feat-uboot-foundation/issue.md)。

## ADR-02 · 固件启动与整机、组件更新

2026-10-10 用户确认：仅当前 i.MX6ULL 板卡，MBR＋ext4，单份整盘 Sparse 配合外部描述；整盘部署包含产品 U-Boot 更新，但本轮 target hash 一致时跳过产品镜像擦写。基础层与 BR/BusyBox 解耦，独立板卡组件更新和已有 Sparse 局部替换均不以完整项目包为前提。旧 FAT32、固定容量及固定路径方案不再是实施前提。

需求和细化讨论分别由 [02 issue.md](../02-feat-uboot-foundation/issue.md) 与 [discussion.md](../02-feat-uboot-foundation/discussion.md) 维护，未决字段和接口不在此重复冻结。[UUU 笔记](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md) 保留协议与历史审查信息，不作为新布局和接口的唯一来源。

## ADR-03 · USB ECM、host DHCP 与 SSH

板级 DT 已描述 `usbotg1` 为 OTG、`usbotg2` 为 host。ROM 下载物理口预期对应 usbotg1，板端功能模式建议固定 peripheral；以 UDC 枚举和物理端口测试最终确认。

建议 Linux configfs 单功能 ECM gadget，由 systemd unit 创建描述符、固定 host/device 两个 locally administered MAC 并绑定指定 UDC；关闭时先解绑。核对 ChipIdea/PHY/UDC、configfs、libcomposite、ECM function 和网络所需 kernel 配置。VID/PID 使用有依据的开发标识，并明确不作为量产 USB 身份。

host 已检测到 Fedora 44、NetworkManager 与 firewalld，外网为 `wlp2s0`。建议专用 USB 网段 `192.168.77.0/24`，host `.1`、板端 DHCP 保留地址 `.2`；应用前检查地址冲突。沿用 NetworkManager 管理 USB 地址和接口生命周期，专用 dnsmasq 只监听 USB 接口、绑定固定 MAC 租约，firewalld 定义 USB 到 WLAN 的转发/NAT策略。实施前复核 NM 自带共享 DHCP 与专用 dnsmasq不同时占用端口，防火墙规则不建立两套所有者。网络脚本启停成对，只移除本次创建的配置，实际写 host 状态时先展示 dry-run。

已确认 root 空密码认证。OpenSSH 需明确允许该方式，核验 PermitRootLogin/PermitEmptyPasswords、认证与 PAM 的真实行为，使客户端无需提示也能完成登录；不能只看 shadow 空字段就声称 ssh 可用。SSH host key 是服务端协议身份，首次启动生成并持久化，镜像不携带所有板卡共用的私钥。

target hostname 为 imx。host 的名称解析是独立职责，建议随专用 USB 开发链路维护固定地址到 imx 的解析，不把 target hostname等同于 host 已能解析。板端 systemd-networkd 使用 DHCP，接收网关与 DNS；解析配置按 BR 的实际安装组件接通。

## ADR-04 · DRM、软件图形与双实例布局

已确认：Mesa 软件 GLES provider，Weston DRM/Pixman，Qt6 Wayland/software。i.MX6ULL 缺少可运行 GLES 的 GPU；PXP 不等同 GLES GPU。[NXP 芯片比较](https://www.nxp.com/docs/en/supporting-information/MICR%20i.MX6UL_6SLL_7D%20Update%20for%20Tech%20Day%20S%26C%20seminars.pdf) 支持这一限制。

03 已有 `DRM_MXSFB`、panel-simple、PWM backlight 和 LCD graph 配置输入，本轮重点是实际 DRM/KMS 输出与用户空间集成。device node中出现 fb兼容节点不影响选用 DRM backend，验收以 Weston 实际输出路径为依据。本地 BR qt6wayland 依赖 GL/GLES provider，Mesa Gallium swrast 提供库；首轮建议 softpipe，不引入 target LLVM/llvmpipe 的额外成本。Qt 设置 `QT_QPA_PLATFORM=wayland`、`QT_QUICK_BACKEND=software`，Weston 显式选择 Pixman，不依赖环境默认猜测。软件 Qt Quick 的 ShaderEffect、粒子等限制见 [Qt 官方说明](https://doc.qt.io/qt-6/qtquick-visualcanvas-adaptations-software.html)。

已确认：本轮通过开机启动编排 launch 两个独立 wt GUI 实例并载入各自默认命令，由 Weston IVI-shell 固定到左右 panel。实施建议为两个固定 surface ID，分别占 LCD `(0,0,512,600)` 与 `(512,0,512,600)`；controller 在 surface 创建/销毁时重新建立对应区域。启动编排由 systemd 管理，IVI-shell 与布局模块负责 surface 到 panel 的映射。

wt 管理实例与命令生命周期；GUI 到 panel 的 attach 及窗口交互由后续独立开发的 shell 管理。本轮只实现两个开机实例的固定 IVI 布局；`wt create` 的成功与 panel 分配独立，创建接口不携带窗口布局策略。

Weston kiosk-shell 的 app-ids 配置选择输出并全屏，不提供单输出两块独立区域。[kiosk-shell](https://wayland.pages.freedesktop.org/weston/toc/kiosk-shell.html) 与 [IVI-shell](https://wayland.pages.freedesktop.org/weston/toc/ivi-shell.html) 是布局依据；实施前核对 Weston `15.0.1` 与 Qt `6.11.1` 的 IVI 客户端插件、协议和 controller ABI，按固定版本接口实现布局模块。

布局模块可以使用 Weston 的 C ABI；com.wt 业务后端仍全部 Rust。bridge 生成的 C++和必要 Qt 启动胶水不承担业务逻辑。配色建议按 Catppuccin Mocha 落地，以文字对比、等宽字体及有限滚动输出为先，性能阈值在 R4 实测后与用户对齐，不预设 60fps 能力。

## ADR-05 · Rust package 与 SDK 两条基线

已确认：采用 Buildroot `2026.08` 的官方依赖基线，Rust/Cargo 为 rust-bin 配方的 `1.97.1`，BR package 与导出的 SDK 使用同一工具链。Rust host 发行包、同版本 host/target rust-std、hash 与 Cargo 基础设施均以该 tag 为准，构建入口按固定源码版本读取配方并记录实际工具身份。

R1 在该基线上固定兼容的 uutils/coreutils 与 Qt Bridge for Rust 发布版本、Cargo.lock 和 external package hash，核验传递依赖最低 Rust 要求、vendor 离线构建及 host/target 隔离。configure/build/sdk 各入口使用同一基线；复用构建目录前核验工具链与配置身份，源码或工具链发生变化时重建受影响产物。ARM 标准库、BR 构建及 SDK 迁移运行待 R1 验证。[coreutils 清单](https://github.com/uutils/coreutils/blob/main/Cargo.toml)、[Qt Bridge for Rust](https://github.com/qt/qtbridge-rust)。

BR package 路线通过 cargo-package/vendor 离线依赖集成 uutils/coreutils，建议安装到独立 libexec 路径，再以明确命令清单接管用户调用。systemd 提供 PID 1 与服务管理，uutils 提供 coreutils 命令；`/bin/sh` 与其他必要系统命令的提供者根据 BR 包依赖固定。命令路径与归属由配置明确指定，systemd/util-linux 所需 mount/login 类工具按 BR 既有约定处理。

日常开发路线由 `make sdk` 导出 host 工具链、sysroot 及必要 host Qt 工具；迁移后运行 SDK relocate 入口。本地 rust-bin 将 rustc、Cargo 和 host/target 标准库安装到 HOST_DIR，make sdk 打包整个 HOST_DIR；R1 选中该包后，这些组件随 SDK 导出。迁移后核验 Rust 运行与目标链接配置，主机准备方法见 [HOST_TOOLCHAIN.md](../../../HOST_TOOLCHAIN.md)。SDK 内使用 host 可执行的 qmake/moc/rcc/wayland-scanner 等生成工具，链接与 pkg-config 查找限定到目标 sysroot。ARM target 预计 `armv7-unknown-linux-gnueabihf`，以 BR 解析结果固定 C linker、C++ compiler、CPU/FPU ABI 与动态加载器。

已确认：使用官方 Qt Bridge for Rust，应用开发面向 Rust 与 QML，CXX 绑定及生成胶水由 bridge 和构建入口封装，对日常开发透明。先用最小 Rust/QML 工程验证 Cargo、host Qt 生成工具与 target Qt 库来源，再进入应用；BR package 与独立 SDK 开发共享版本锁和业务源码。参考 [BR SDK 方法](https://buildroot.org/downloads/manual/manual.html#_using_the_generated_toolchain_outside_buildroot)、[Qt Bridge for Rust](https://github.com/qt/qtbridge-rust)。

待验证：Qt Bridge for Rust 官方当前 README 要求 Rust/Cargo ≥ `1.88`、Qt ≥ `6.10`，BR 基线的 Rust `1.97.1` 与 Qt `6.11.1` 满足这两项版本要求。官方列出的支持平台未覆盖 ARMv7；R1/R4 需验证固定 bridge 发布版的 ARMv7 交叉构建、软件 Qt Quick、IVI 客户端及 SDK 迁移运行。版本核对不表示这些路径已获上游支持或通过实测。

## ADR-06 · wt、PTY、日志与触摸

已确认：SSH 用于进入板卡和承载调用端交互，板端 wt CLI 连接本地 Rust 服务。wt 负责实例与命令生命周期，GUI 只读订阅输出；窗口 attach 与交互由 ADR-04 所述独立 shell 管理。建议 Unix socket 与 Rust SDK 共享创建、列表、指定 ID 执行及日志接口。daemon 持有实例状态、子进程和内部 PTY；GUI 重启仅重新订阅已有实例。

已确认：每个实例同时运行一个命令，busy 时拒绝新命令并向调用端报告。`wt id <id> -- <cmd> [args...]` 将 argv 原样交给目标实例的新子进程，复杂 shell 表达式由调用者显式传 `sh -lc '...'`。执行输出及完成 result 回显给调用端 PTY，CLI 返回命令退出状态；不存在 ID、busy、创建失败及非零退出均有明确结果。CLI 附着期间转发输入与 Ctrl-C，并恢复调用端终端状态。

已确认：`wt create` CLI/SDK 创建独立会话实例并返回可复用 ID，实例的会话进程通过 `setsid()` 脱离调用端会话与控制终端。实例生命周期与调用端 SSH PTY 解耦，SSH 断开后实例及运行中的命令继续由板端管理。内部命令 PTY 的 master 由 daemon 持有并持续读取，命令需要终端时在独立会话中建立控制终端；`setsid()` 本身不关闭继承的文件描述符，实施需一并处理 stdin/stdout/stderr、挂断信号与输出背压，不能依赖调用端持续连接维持运行。断连后交互命令的输入等待及后续终止方法在接口实施时明确并验证。

PTY 会合并终端输出流；首轮保留输出字节/有序文本。GUI 采用有界输出缓存与批量更新，丢弃历史时提供可见截断状态。

Rust fastfetch 原型采集 hostname/kernel/uptime/memory/CPU 等本机信息；Rust userlog 提供本地日志发送 CLI、Rust SDK 和订阅展示命令。开机编排创建两个实例，launch 两个 GUI 并载入各自默认命令，Weston IVI-shell 固定左右 panel；systemd 管理启动依赖与进程，GUI 启动等待 Weston 可连接。

触摸服务通过 udev稳定识别 GT911 event设备，读取 evdev并按 SYN_REPORT组帧，记录 contact/坐标/状态与时间后写入 userlog。不得 EVIOCGRAB独占输入；libinput/Weston仍收到同一设备事件。拔插或重建节点由设备生命周期触发重新连接；若出现 SYN_DROPPED按evdev协议处理，不把丢失事件拼成正常轨迹。原始事件与屏幕坐标变换需分别核验，只有有效转换后才报告屏幕坐标。
