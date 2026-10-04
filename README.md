# ea-emb-linux

面向嵌入式 Linux 板卡的主线适配工程，目标是基于 Linux LTS 内核、U-Boot 和 Buildroot，建立可维护、可复现的启动、系统构建与板级支持流程。

项目优先推进主线支持，并以 LTS 内核作为长期维护目标。目前处于仓库初始化阶段，纳入的源码版本是适配起点；具体 LTS 基线与支持范围将在板卡验证后确定。

## 计划适配板卡

| 板卡 | SoC | 状态 |
| --- | --- | --- |
| `100ask_imx6ull_pro` | NXP i.MX6ULL | 计划适配 |
| `tspi_rk3566` | Rockchip RK3566 | 计划适配 |

适配工作包括引导链、设备树、内核配置、根文件系统构建，以及板卡外设验证。当前尚未完成板卡启动与功能验证。

## 源码组织

三个主线源码仓库以 Git submodule 管理，父仓库记录各自的确切提交：

| 路径 | 用途 | 适配起点 |
| --- | --- | --- |
| `sdk/vendor_mainline/linux-7.2.9` | Linux 内核与驱动 | Linux 7.2.9 源码快照 |
| `sdk/vendor_mainline/uboot-2026.07` | U-Boot 引导程序 | U-Boot v2026.07 源码快照 |
| `sdk/vendor_mainline/buildroot-2025.02` | 工具链、根文件系统与镜像构建 | Buildroot 2025.02.x 分支源码快照 |

子模块跟随各自仓库的 `main` 分支，首次提交保留导入时的源码内容，并记录上游来源提交。`sdk/` 下其余内容作为本地 SDK 和参考资料使用，不纳入父仓库。

## 获取源码

```sh
git clone --recurse-submodules https://github.com/yceachan/ea-emb-linux.git
cd ea-emb-linux
```

已经克隆父仓库时，初始化或恢复到父仓库记录的源码版本：

```sh
git submodule update --init --recursive
```

需要主动更新到三个子模块各自的最新 `main` 时：

```sh
git submodule update --remote --checkout
```

更新并验证后，应在父仓库提交新的子模块引用，以便其他人复现相同版本。

## 许可

本项目原创文档采用 [MIT 许可证](LICENSE)。

涉及的上游 SDK、内核、U-Boot、Buildroot 及第三方组件保留各自原有的开源许可证和版权声明，以对应源码中的 `COPYING`、`LICENSE`、SPDX 标识及组件许可文件为准。文档的 MIT 许可证不覆盖这些源码，也不改变其许可条款。
