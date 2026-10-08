# 03 · Kernel / BusyBox 阶段交付关闭

关闭日期：2026-10-09。用户确认目标镜像已完成实物烧录，并已进入板上 shell，要求关闭本工作区。

## 交付结果

已交付固定源码基线、板级 DTS 与配置、kernel/DTB 构建入口、静态 BusyBox 配置和 rootfs 文件树，以及带 `/boot` 文件的 p2 ext4 镜像部署入口。现有烧录日志记录目标 p2 写入完成；板上 shell 的完成状态来自本轮用户确认。

关闭依据：`artifacts/2026-10-09-close/collection.json`。

## 关闭范围与后续归属

本阶段以目标镜像落盘并进入 BusyBox shell为关闭边界。RAM rescue 已取消，自动引导由 [04 issue](../../../../04-br-rtfs-integration/.issues/open/01-feat-br-system/issue.md) 的新 U-Boot 基线承接；本工作区保留已有 U-Boot 的手工启动方法。

原验收表中的 DDR 专项数据测试、eMMC 重启读回、shell 控制与退出重入，以及运行时身份和写后校验，当前没有完整的新系统实测记录，关闭状态不将它们标记为逐项通过。LCD、触摸与 USB ECM 在 04 验证；HDMI、AP3216C、无线功能仍按既有边界延后。

03 的 kernel/DTB 输入继续作为 04 的引用来源，本阶段配置和源码输入在此归档。
