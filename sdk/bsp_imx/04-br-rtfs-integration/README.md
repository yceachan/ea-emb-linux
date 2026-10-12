# Buildroot 开发板系统集成

本里程碑工作区为 `sdk/bsp_imx/04-br-rtfs-integration/`。

目标和验收由 [.issues/open/01-feat-br-system/issue.md](.issues/open/01-feat-br-system/issue.md) 维护，技术选择由 [adr.md](.issues/open/01-feat-br-system/adr.md) 维护，实施顺序由 [route.md](.issues/open/01-feat-br-system/route.md) 维护，当前状态见 [progress.md](.issues/open/01-feat-br-system/progress.md)。

uuf/U-Boot 基础层由 [.issues/open/02-feat-uboot-foundation/](.issues/open/02-feat-uboot-foundation/issue.md) 独立维护，技术选择见 [adr.md](.issues/open/02-feat-uboot-foundation/adr.md)，实施顺序见 [route.md](.issues/open/02-feat-uboot-foundation/route.md)。2026-10-12 对齐作为当前需求来源，源码与 GUI/CLI 产品工作区为 `uuf/`。BR/BusyBox 均作为外部消费者。

当前完成需求与路线对齐，`uuf/` 实现和固件迁移待推进；历史实施轨迹见 issue 01 的 progress.md。02 保留既往里程碑，kernel 输入仍由 03 维护。BR 集成及实板验收待实施；耗时完整构建由开发者审阅执行，默认 `-j12`。

主机检查结果与工具供应方式见 [HOST_TOOLCHAIN.md](HOST_TOOLCHAIN.md)。

[UUU 用法与主机烧录方案](../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)
