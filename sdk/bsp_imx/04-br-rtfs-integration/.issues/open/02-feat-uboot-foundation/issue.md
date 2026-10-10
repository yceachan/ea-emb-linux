---
title: 02 · i.MX6ULL UUU ram loader基线
tags: [U-Boot, UUU, i.MX6ULL, Sparse, ext4]
note_types: document
created: 2026-10-10
updated: 2026-10-10

---

# 02 · i.MX6ULL UUU ram loader基线 。

## 1.uuu ram loader

基于 02工程的板卡 DDR、UART、USB、eMMC，fastboot 基线迭代开发。

将本项目的uboot基线配合现有uuu version ，在host上提供对Linux 和RTFS镜像的一键烧录能力。

将`04/uboot`视为一个适配的imx6_pro板卡的增强型uuu 烧录工具产品，bundle一个适配板卡的uboot固件基线，提供cli 和 tarui GUI，size 屏幕中心1/4 屏。

能力矩阵：

| U1 硬件与启动         | 仅适配当前板卡。支持 ROM USB 下载后自动进入下载服务          |
| --------------------- | ------------------------------------------------------------ |
| U2 路径与描述         | 主机源码、工具链、构建、固件、组件、输出及日志路径由参数或shell变量提供，不要求固定仓库位置或 CWD。设备、硬件区域、分区信息及镜像内文件路径由板卡／外部布局和启动描述提供。源码继续维护在 04/uboot/。 |
| U3 emmc layout        | uboot MBR FAT32 分区， kernel / rtfs 双 ext4分区。支持单独和组合烧录修改uboot ， kernel ，dtb ，rtfs |
| U4 sparse             | ext4文件系统，打包成aosp sparse镜像烧录，避免累赘写零。      |
| U5 独立板卡更新       | 直接消费 kernel、DTB 或 rtfs Sparse 以及目标描述，只定向更新/擦除指定组件； |
| U6 独立uboot部署      | 提供仅部署产品 U-Boot 的入口，不依赖系统镜像；包含目标、启动配置、读回与冷启动验证规则。不得以整盘烧录代替独立固件部署。。 |
| U7 分区信息修改和展示 | 通过独立的profile文本文件配置分区描述，然后在target emmc 部署相应分区。在GUI展示实际分区与烧录镜像信息，分区可修改。<br />复核各个分区所需的大小，给够预留量，生成一个默认分区表。 |
| U8 整盘sparse部署     | 提供将分区表，uboot , kernel , dtb ,rtfs 打包成单个归档文件 以及反向拆解的能力，本工具可以消费此归档文件，烧录板卡emmc相应组件。 |
| U8 检查与计划         | 检查输入格式、容量、布局、写入范围和组件定位；信息不足或有多个候选时要求明确选择，不猜测固定文件名或分区。source 文件名不决定 target 文件名。 |
| U9 安全与验证         | dry-run 只检查主机输入与计划，不下载、不写板；正式操作仍先预检，再展示目标和范围并二次确认。实际 loader 启动后、持久写入前复核真实设备信息与布局，写后核验。错误、断连和比较失败停止后续操作，不自动回滚。 |
| U10 构建与交付        | 代理不执行真实硬件写操作。交付可复现输入、完整操作文档和分层证据，不用主机测试替代实板验收。 |



## 2.产品 U-Boot：

本uboot 固件复用为实际烧录到emmc 的固件，当从emmc启动固件时，去引导内核。

启用发行版启动机制，可以通过extlinux.conf 配置启动选项，可以

启动wait 3s ，任意键进入uboot 控制台。

bootmenu 后续支持从板载rtfs / 网络rtfs 启动，以此对齐USB_ECM。先保留扩展点,到时候从板载rtfs进去，在发行版配置网络rtfs启动项。

## 3. 验收条件

将本uboot 固件 和 03 的kernel；busybox rtfs 做为归档镜像，通过ram loader烧录emmc ，然后验证每个单独组件的擦除和单独替换。在busybox发行版配置uboot启动项，此后默认引导这个busybox。
