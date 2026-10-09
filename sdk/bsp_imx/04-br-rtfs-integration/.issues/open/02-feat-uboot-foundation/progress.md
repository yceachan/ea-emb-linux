---
title: U-Boot 基础层对齐进度
tags: [U-Boot, UUU, issue]
note_types: document
created: 2026-10-10
updated: 2026-10-10

---

# 对齐进度

## 2026-10-10 · 建立独立专章

用户确认完整需求稿前七条，并补充：仅当前 i.MX6ULL 板卡；MBR＋ext4；单份整盘 Sparse 配合外部描述；整盘部署更新产品 U-Boot，但本轮实际 target hash 一致时跳过产品镜像擦写。

已建立 [issue.md](issue.md) 作为本基础层需求和验收来源，[discussion.md](discussion.md) 细化布局、启动、ext4、Sparse、hash 和接口未决项。父级 BR issue 继续维护系统目标，U-Boot 不再以 BusyBox/BR 的目录、版本或完整包为前提。

本轮只修改对齐文档与导航，不改固件／主机工具，不执行构建、UUU 或硬件操作。上一轮探索 worktree 的未合入代码不作为本专章实现。已有 FAT32、固定容量、固定路径和 BusyBox 验收产物保留为历史事实，不作为新 MBR/ext4 需求的通过证据。

当前下一项是 D1：启动文件与 rtfs 是否采用两个独立 ext4 区域。直接替换同一分区的 rtfs Sparse 会覆盖其中的 kernel/DTB，必须先决定如何满足组件保留要求，不能静默选定旧 p1/p2 方案。没有新实板证据，issue 保持 open。
