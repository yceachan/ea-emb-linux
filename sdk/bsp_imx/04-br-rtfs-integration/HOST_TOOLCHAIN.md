---
title: 04 主机构建环境与 SDK 准备
tags: [Buildroot, toolchain, Rust, Qt6]
note_types: document
created: 2026-10-09
updated: 2026-10-09

---


# 04 主机构建环境与 SDK 准备

04 使用 Buildroot 官方 tag `2026.08` 及其依赖基线，用户空间的编译器、sysroot、Qt 生成工具和 Rust 工具由同一次 BR 构建供应，并随 SDK 导出。现有 ARM GNU 工具链继续用于固件构建。本文区分既有主机审查证据与新基线准备要求；构建目录由 [ADR-01](.issues/open/01-feat-br-system/adr.md) 维护。

## 1. 主机检查结果

既有审查在 BR `2025.02.18` 上运行了 `support/dependencies/dependencies.sh`，启用 UTF-8 locale 检查，基础依赖检查通过。六个必需 Perl 模块均可加载；原生 C 和 C++17 程序均完成编译、链接与运行。04 的板级 defconfig 尚未实现，这些证据不替代 `2026.08` 新基线的依赖检查与完整包集构建验收。

| 项目 | 本机状态 | 用途 |
|---|---|---|
| 主机系统 | Fedora 44，x86_64 | BR 构建主机 |
| 原生 GCC/G++ | 16.2.1，基本编译与运行通过 | 构建 host packages |
| Make、下载与归档工具 | 本地 BR 基础检查通过 | 构建及源码获取 |
| Perl | 六个必需模块齐全 | Autoconf、Automake、OpenSSL 等 host 构建 |
| ncurses、OpenSSL、libusb、zlib 开发文件 | 已有；zlib 由 `zlib-ng-compat-devel` 提供 | 配置界面和相关主机工具 |
| Python | 3.14.7，pyserial 3.5 可导入 | 主机脚本与串口工具 |
| genimage | 19，`/usr/bin/genimage`，已由用户通过 dnf 安装 | 主机镜像组装 |
| dtc | 1.8.1，`/usr/bin/dtc`，已由用户通过 dnf 安装 | 主机设备树工具 |
| gperf | 3.2.1，`/usr/bin/gperf`，已由用户通过 dnf 安装 | 主机代码生成工具 |
| ARM GNU GCC | 15.3.1，编译器可执行 | 既有 U-Boot/kernel 构建 |
| 用户目录 Rust | rustc/Cargo 1.99.0，仅安装 x86_64 标准库 | 当前主机开发环境 |

审查索引：`artifacts/2026-10-09-host-toolchain-audit/collection.json`。

## 2. 工具供应方式

| 工具 | 本地 BR 行为 | 准备方式 |
|---|---|---|
| CMake | `2026.08` 的 `check-host-cmake.sh` 按最低版本检查，可接受满足条件的 4.x | 按配置复用合格系统 CMake 或构建 host-cmake `4.4.0` |
| Meson、Python | host-meson 配方使用 BR Python 包设施 | 使用 BR 的 host-meson 与 host-python3 `3.14.7` |
| genimage、dtc、gperf | 系统工具已安装；BR 有对应 host 配方 | 系统工具可直接调用，BR 包声明的 host 依赖仍按其配方构建 |
| ARM C/C++ 与 libc | BR 可构建匹配目标系统的工具链 | 随 rootfs 构建并导出 SDK |
| Qt6 生成工具 | qt6base 依赖 host-qt6base，使用 `QT_HOST_PATH` | 随 BR 构建匹配 Qt `6.11.1` 的 host 工具 |
| Rust 与 ARM 标准库 | rust-bin 将 rustc、Cargo、host/target 标准库安装到 `HOST_DIR` | 使用官方配方 `1.97.1`，随 SDK 导出 |

本地 `make sdk` 打包整个 `HOST_DIR`。因此，在板级配置中选中 rust-bin 后，SDK 会包含该配方安装的 Rust 组件；Qt 工具同样以实际选中的 host packages 为准。SDK 迁移后执行 `relocate-sdk.sh`，再验证 Rust、Qt 工具和交叉链接器的路径。

镜像转换工具的安装来源和验证方法统一见下方笔记。

[UUU 用法与主机烧录方案](../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## 3. 准备顺序

1. 保持当前主机基础依赖，按集中笔记准备镜像转换工具并验证实际功能。
2. 按 ADR-05 使用 `2026.08` 官方依赖基线：Rust `1.97.1`、Qt `6.11.1`、Weston `15.0.1`；固定兼容的 coreutils/Qt Bridge for Rust 发布版本及 Cargo.lock，并核验 ARM target 与交叉构建配置。
3. 形成 04 的配置及构建入口。固件构建使用现有 ARM GNU 工具链；BR 构建使用原生 HOSTCC/HOSTCXX；用户空间开发使用导出的 BR SDK。各入口明确编译器和库搜索路径。
4. 由开发者执行 BR 构建和 SDK 导出，默认 `-j12`。迁移 SDK 后，用独立 Cargo 程序和最小 Qt bridge 工程核验编译、链接和板端运行。

现有 `profile/prebuilt.env` 设置 ARM 的 CC/CXX，供固件构建使用。BR 和 SDK 入口应分别设置自己的编译环境。当前审查进程的 CC/CXX、库搜索路径和 Rust 编译参数均未预设交叉配置。

## 4. 仍需固定的实施输入

官方依赖版本、hash 与验证边界由 [ADR-05](.issues/open/01-feat-br-system/adr.md#adr-05--rust-package-与-sdk-两条基线) 维护；日常 SDK 开发使用 BR 导出的 Rust `1.97.1`。coreutils/Qt Bridge for Rust 发布版本、external package hash、ARM target 和 Cargo.lock 仍需在 R1 固定。Qt Bridge for Rust 的最低版本要求由当前基线满足，ARMv7 交叉构建、配套 host Qt 工具及 SDK 迁移运行仍需实测。

当前 GCC 16 的检查证明原生编译器、链接器和运行库可用；全部 host packages 的兼容性仍需实际 BR 构建验证。发生具体失败时，按包的源码和补丁处理，不从版本号单独推断必须更换主机系统。
