---
title: uuf · 技术决策
tags: [uuf, MBR, Sparse, ext4]
note_types: document
created: 2026-10-12
updated: 2026-10-13
template: doc
lang: zh

---

# 技术决策

2026-10-13 修订：归档携带最终 MBR，以其为分区几何事实源。需求与验收以 [issue.md](issue.md) 为来源，本文件记录技术决策；不表示失败实现已恢复。

## ADR-01 · 工作区与主机入口

产品维护在 `04-br-rtfs-integration/uuf/`，CLI 名称为 `uuf`。GUI 使用 Tauri，前端使用 React。CLI 与 GUI 共用组件定位、计划、UUU 执行和验证后端；GUI 不建立第二套烧录逻辑。

U-Boot 板级输入从 02 的固定 revision、overlay、注册补丁和工具链迁入本工作区维护。03 保留 kernel/DTB 输入归属；BR 与 BusyBox 是外部载荷消费者。构建及产物路径由参数或环境提供。

## ADR-02 · eMMC 与启动路径

产品 U-Boot 裸写 eMMC boot0；user area 使用 MBR，分为 kernel ext4 与 rtfs ext4。ROM 读取固件原始块，不经过文件系统。

kernel、DTB 与 `/extlinux/extlinux.conf` 位于 kernel 分区。U-Boot 的文件路径相对于该分区根目录；Linux 将该分区挂载到 `/boot`，rtfs 分区挂载到 `/`。Linux 的 MMC 编号不因 U-Boot 的编号为 1 就自动确定，按实测设备与分区标识对应。

默认固件发现 extlinux 配置，启动项由运行系统维护。沿用 02 的 RAM 环境起点，不因管理启动项而新增持久化环境。固件要区分 ROM USB 下载与 eMMC 启动；USB 路径自动进入 fastboot，eMMC 路径提供 3 秒控制台打断后按 extlinux 引导。

boot0 写入偏移沿用 02 的 `0x400` 基线；实施时核对实际构建镜像、区域容量与 EXT_CSD 启动设置。产品固件的目标字节 hash 一致时跳过擦写，启动设置仍独立检查。

## ADR-03 · 一键部署与独立更新

一个主机操作消费归档文件，编排产品固件、MBR、kernel 分区 Sparse 和 rtfs Sparse 的部署。解包作为工具内部准备步骤；独立解包入口用于取出组件。

归档保存最终 MBR、两张分区 Sparse、固件、独立更新所需的原始组件与清单。本文以 `mbr.bin` 指代分区表文件；载荷文件通过清单显式关联目标，不依赖固定文件名猜测。

清单记录组件到 MBR 表项的映射及文件校验。分区起点、长度、类型、活动标志和磁盘 signature 只从 MBR 读取，不在清单或 JSON profile 中重复维护。固件部署描述单独给出 boot0 范围与启动设置。

kernel／rtfs 角色通过明确的组件映射解释，不能把 MBR 分区类型或活动标志单独当成角色名称。制像、计划与部署使用同一份归档 MBR。

整分区部署使用 AOSP Sparse，按文件系统分配信息跳过空闲块。RAW/FILL 的有效内容必须写入；DONT_CARE 保留介质原内容。写后核验有效写入范围，不能用补零展开后的整盘 hash 代表介质一致性。

kernel/DTB 独立替换使用原始文件和 ext4 文件写入，保留其他文件及分区。rtfs 独立替换使用分区 Sparse。kernel/DTB 不要求单独删除；擦除只面向明确固件范围或完整分区。

02 当前只有 ext4 读取，fastboot buffer 与 heap 各为 16 MiB。实施先验证 ext4 特性、文件覆盖、heap/journal 和 RAM 范围。若真实输入不能通过，应对齐替代路线；不得用整个 kernel 分区重写冒充独立文件更新。

## ADR-04 · 布局生成与更新

GUI 将 MBR 解析为可编辑分区表，修改后生成新的 MBR。默认布局按载荷与预留量计算；这些是镜像准备输入，最终容量写入 MBR，不作为第二份部署几何保存。

打包按 MBR 容量制作 kernel、rtfs 两个新 ext4，再生成 AOSP Sparse。Sparse 的逻辑长度按 `blk_sz × total_blks` 计算；不能用容器文件长度代表目标分区容量。启动描述在制像时与 rtfs 映射核对，固件部署信息保持独立。

布局更新必须同时部署新的 MBR 与两张匹配的 ext4 镜像。缺少任一镜像时拒绝，不提供单独写分区表的布局更新入口。即使只改动一个分区，也重建两个 ext4。

新文件系统不再引用旧目录与文件；DONT_CARE 可以保留旧介质字节。不要求物理 MMC erase，独立擦除仍按明确范围处理。

实际设备容量由探测获得。检查所有分区不重叠、不越界；容量更大时保留归档几何，剩余空间不自动分配。若要扩展布局，应重新准备 MBR 与匹配镜像。

独立组件更新核对实际布局与目标映射，不更改 MBR。布局更新则检查旧状态与计划的确认对象一致，不能要求新 MBR 事先等于旧 MBR。启动配置独立修改不触发双 ext4 重建。

## 实现依据

[U-Boot extlinux](https://docs.u-boot.org/en/stable/develop/bootstd/extlinux.html)、[ext4 写入约束](https://docs.u-boot.org/en/stable/usage/filesystems/ext4.html)、[MMC 区域与启动设置](https://docs.u-boot.org/en/stable/usage/cmd/mmc.html)、[MBR 结构](https://uefi.org/specs/UEFI/2.11/05_GUID_Partition_Table_Format.html#legacy-master-boot-record-mbr)、[AOSP Sparse 格式](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/sparse_format.h)。

现有验收载荷的尺寸与身份见 `artifacts/2026-10-12-uuf-alignment/collection.json`。
