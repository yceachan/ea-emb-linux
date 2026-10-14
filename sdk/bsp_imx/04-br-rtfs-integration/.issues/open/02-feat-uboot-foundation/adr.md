---
title: uuf · 技术决策
tags: [uuf, MBR, Sparse, ext4]
note_types: document
created: 2026-10-12
updated: 2026-10-15
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

仅映射的 kernel 分区带活动标志，避免固件扫描 rtfs 中的其他启动配置。kernel、DTB 与 `/extlinux/extlinux.conf` 位于 kernel 分区。U-Boot 的文件路径相对于该分区根目录；Linux 将该分区挂载到 `/boot`，rtfs 分区挂载到 `/`。Linux 的 MMC 编号不因 U-Boot 的编号为 1 就自动确定，按实测设备与分区标识对应。

默认固件发现 extlinux 配置，启动项由运行系统维护。沿用 02 的 RAM 环境起点，不因管理启动项而新增持久化环境。固件要区分 ROM USB 下载与 eMMC 启动；USB 路径自动进入 fastboot，eMMC 路径提供 3 秒控制台打断后按 extlinux 引导。

boot0 写入偏移沿用 02 的 `0x400` 基线；实施时核对实际构建镜像、区域容量与 EXT_CSD 启动设置。产品固件的目标字节 hash 一致时跳过擦写，启动设置仍独立检查。

## ADR-03 · 一键部署与独立更新

一个主机操作消费归档文件，编排产品固件、MBR、kernel 分区 Sparse 和 rtfs Sparse 的部署。解包作为工具内部准备步骤；独立解包入口用于取出组件。

归档保存最终 MBR、两张分区 Sparse、固件、独立更新所需的原始组件与清单。本文以 `mbr.bin` 指代分区表文件；载荷文件通过清单显式关联目标，不依赖固定文件名猜测。

清单记录组件到 MBR 表项的映射及文件校验。分区起点、长度、类型、活动标志和磁盘 signature 只从 MBR 读取，不在清单或 JSON profile 中重复维护。固件部署描述单独给出 boot0 范围与启动设置。

kernel／rtfs 角色通过明确的组件映射解释，不能把 MBR 分区类型或活动标志单独当成角色名称。制像、计划与部署使用同一份归档 MBR。

整分区部署使用 AOSP Sparse，按文件系统分配信息跳过空闲块。RAW/FILL 的有效内容必须写入；DONT_CARE 保留介质原内容。写后核验有效写入范围，不能用补零展开后的整盘 hash 代表介质一致性。

kernel/DTB 独立替换使用原始文件和 ext4 文件写入，保留其他文件及分区。rtfs 独立替换使用分区 Sparse。kernel/DTB 不要求单独删除；擦除只面向明确固件范围或完整分区。

02 基线的 fastboot buffer 与 heap 各为 16 MiB。本轮将完整文件窗口扩大到 32 MiB，heap 保持 16 MiB；实际 ext4 写入器已验证 32 MiB 边界载荷，具体地址与约束见 [firmware/README.md](../../../uuf/firmware/README.md)。若真实输入不能通过，应对齐替代路线；不得用整个 kernel 分区重写冒充独立文件更新。

## ADR-04 · 布局生成与更新

GUI 将 MBR 解析为可编辑分区表，修改后生成新的 MBR。默认布局按载荷与预留量计算；这些是镜像准备输入，最终容量写入 MBR，不作为第二份部署几何保存。

打包按 MBR 容量制作 kernel、rtfs 两个新 ext4，再生成 AOSP Sparse。Sparse 的逻辑长度按 `blk_sz × total_blks` 计算；不能用容器文件长度代表目标分区容量。启动描述在制像时与 rtfs 映射核对，固件部署信息保持独立。

布局更新必须同时部署新的 MBR 与两张匹配的 ext4 镜像。缺少任一镜像时拒绝，不提供单独写分区表的布局更新入口。即使只改动一个分区，也重建两个 ext4。

新文件系统不再引用旧目录与文件；DONT_CARE 可以保留旧介质字节。不要求物理 MMC erase，独立擦除仍按明确范围处理。

实际设备容量由探测获得。检查所有分区不重叠、不越界；容量更大时保留归档几何，剩余空间不自动分配。若要扩展布局，应重新准备 MBR 与匹配镜像。

独立组件更新核对实际布局与目标映射，不更改 MBR。布局更新则检查旧状态与计划的确认对象一致，不能要求新 MBR 事先等于旧 MBR。启动配置独立修改不触发双 ext4 重建。

## ADR-05 · M2 的执行与审阅边界

CLI 使用 Python 后端，UUU 负责 ROM 下载和 fastboot 传输，e2fsprogs 负责制像与主机文件系统检查。CLI 和后续 Tauri GUI 通过同一套操作参数、计划及 JSON Lines 事件调用后端；确认由调用者回复随机 token，取消必须等待执行进程组清理。操作入口和接口实现见 [uuf/README.md](../../../uuf/README.md)。

正式任务先完成主机暂存、hash、格式与离线脚本检查。第一次确认允许 RAM loader 与设备探测；取得 CID、容量、MBR 和启动路径后再形成范围计划，第二次确认才允许持久写入。确认后重探目标并复核暂存 hash，写入脚本内再次核对已确认 extlinux 的长度与摘要；有变化时停止，已写内容不回滚。dry-run 在第一阶段结束，缺少的真实设备信息明确标为待检查。

空盘基础探测只要求 CID、容量、启动设置与原始 MBR。独立系统组件操作还从实际 extlinux 的 LABEL、文件路径和 root PARTUUID 确定当前角色，并与输入映射比较；多个候选必须明确选择。APPEND 或 DEFAULT 的合法独立修改不要求重建文件系统。固件单独更新不依赖有效产品分区表。

Sparse 按 ext4 分配块生成，RAW／FILL 均按实际内容写入和核验；DONT_CARE 只保护写前字节未被改变。计划分别保留源容器大小、逻辑长度、分区容量和有效写入长度，禁止以其中一个替代另一个。未知额外文件的保留不能仅凭已知文件摘要声称通过验收。

layout 与 pack 共用 ext4 格式化参数，按载荷及文件数测量空文件系统的实际元数据开销，迭代容量直到可用空间覆盖载荷与预留量。最终 pack 仍检查实际剩余空间；不使用固定 16 MiB 元数据余量推断大 rootfs 容量。

M2 当前支持当前板卡、两项 Linux MBR 主分区、4 KiB 块且无 CRC 扩展的 Sparse。含 ACL／扩展属性的 tar 和特殊文件 hardlink 明确拒绝；目录树保留已有常规 hardlink、所有权及扩展属性。制像与协议检查不能代替实板写入、Linux MMC 映射和冷启动证据。M2 出口仍要求独立 PR 的云端 review 与开发者人工审阅；M3 尚未开始。

## 实现依据

[U-Boot extlinux](https://docs.u-boot.org/en/stable/develop/bootstd/extlinux.html)、[ext4 写入约束](https://docs.u-boot.org/en/stable/usage/filesystems/ext4.html)、[MMC 区域与启动设置](https://docs.u-boot.org/en/stable/usage/cmd/mmc.html)、[MBR 结构](https://uefi.org/specs/UEFI/2.11/05_GUID_Partition_Table_Format.html#legacy-master-boot-record-mbr)、[AOSP Sparse 格式](https://android.googlesource.com/platform/system/core/+/refs/heads/main/libsparse/sparse_format.h)。

现有验收载荷的尺寸与身份见 `artifacts/2026-10-12-uuf-alignment/collection.json`。

## ADR-06 · 本轮内存预算收口

2026-10-15，开发者确定完整文件窗口为 32 MiB。下载 buffer 为 `[0x82000000, 0x84000000)`，kernel 启动加载区为 `[0x80800000, 0x82800000)`；DTB 从 `0x88000000` 加载，extlinux 配置从 `0x8a000000` 加载。下载服务与内核启动分时使用 RAM，启动数据放在低 128 MiB 区域外。

host 输入校验、M1 固件配置与板端下载长度一致；不引入文件分块会话。heap 保持 16 MiB，按实际写入器峰值验证。32 MiB 大小载荷只证明覆盖与保留行为，不能冒充可启动内核或实板解压证据。后续真实 kernel 若超过此预算，应重新对齐内存布局；本轮在此上限收口。
