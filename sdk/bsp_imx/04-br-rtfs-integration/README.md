# Buildroot 开发板系统集成

本里程碑工作区为 `sdk/bsp_imx/04-br-rtfs-integration/`。

目标和验收由 [.issues/open/01-feat-br-system/issue.md](.issues/open/01-feat-br-system/issue.md) 维护，技术选择由 [adr.md](.issues/open/01-feat-br-system/adr.md) 维护，实施顺序由 [route.md](.issues/open/01-feat-br-system/route.md) 维护，当前状态见 [progress.md](.issues/open/01-feat-br-system/progress.md)。

U-Boot 基础层现由 [.issues/open/02-feat-uboot-foundation/](.issues/open/02-feat-uboot-foundation/issue.md) 独立维护，细化讨论见 [discussion.md](.issues/open/02-feat-uboot-foundation/discussion.md)。用户已确认仅当前板卡、MBR/ext4、外部描述及产品 target hash 相同免擦写；通用接口、ext4 分区组织与更新能力尚未完成实现。BR/BusyBox 均作为外部消费者，不绑定核心路径、版本或完整包。

本轮实现源码仍组织在 `uboot/`，04 根目录留给 BR/kernel 集成。既有 FAT32/BusyBox 原型、验收镜像及 [历史操作说明](uboot/FLASHING.md) 保留供审查，不代表新确认的基础层已通过。02 保留既往里程碑，kernel 输入仍由 03 维护。BR 集成及实板验收待实施；耗时完整构建由开发者审阅执行，默认 `-j12`。

主机检查结果与工具供应方式见 [HOST_TOOLCHAIN.md](HOST_TOOLCHAIN.md)。

[UUU 用法与主机烧录方案](../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)
