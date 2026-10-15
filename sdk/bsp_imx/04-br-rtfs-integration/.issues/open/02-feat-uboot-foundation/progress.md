---
title: uuf · 三阶段开发进度
tags: [uuf, milestone, review]
note_types: document
created: 2026-10-13
updated: 2026-10-15
template: doc
lang: zh

---

# uuf · 三阶段开发进度

本轮使用新 worktree 按 [route.md](route.md) 推进。每阶段完成主机验证、独立 PR 的云端 review 和开发者人工审阅后，才进入下一阶段。实板行为有独立证据门槛。

## 工作区

路径：`/home/pi/worktrees/ea-emb-linux/codex/uuf-milestones`。

需求基线：`codex/uuf-baseline`，提交 `f5598ee`；包含当前 issue 与失败实现参考。该分支承接本地 main 尚未发布的提交，阶段 PR 基于它审阅。

| 阶段 | 分支与 PR | 状态 |
|---|---|---|
| M1 U-Boot | `codex/uuf-uboot`，[PR #1](https://github.com/yceachan/ea-emb-linux/pull/1) | 完整构建与主机验证通过，云端复审未发现重大问题；开发者已授权进入 M2 |
| M2 host flasher | `codex/uuf-host-flasher`，[PR #2](https://github.com/yceachan/ea-emb-linux/pull/2) | CLI 与真实载荷集成通过，32 MiB 调整与 32 项主机检查通过，容量修正待云端复审，人工审阅待完成 |
| M3 GUI | 待 M2 人工审阅后创建 | 未开始 |

## M1 的实现与验证

迁入固定 U-Boot 板级输入、ROM USB／eMMC 启动分流、extlinux 和 3 秒打断，以及板端文件写入、固件范围保护、hash 门控和启动设置核验。实现说明与操作入口见 [firmware/README.md](../../../uuf/firmware/README.md)。

原生验证直接编译生产板级命令和配置后的 U-Boot ext4 源码，使用内存或普通文件介质。补齐 journal superblock 数据读取的准确故障注入，并将文件系统特性／journal 状态检查前移到写入器初始化之前。拒绝 unlink 写入器无法释放索引块的 extent 树。

2026-10-13，开发者允许本 session 执行 SDK 构建集成，并指示构建 U-Boot 后进入 host flasher CLI。固定输入的完整 U-Boot 构建已通过，release 生成 DCD 镜像及可核对的六项文件清单。ROM USB 自动 fastboot、eMMC 冷启动、3 秒打断及实板文件更新仍待验收。

本次完整构建的复现命令：

```sh
env CROSS_COMPILE=/home/pi/ea-emb-linux/sdk/vendor_mainline/toolchains/arm-gnu-toolchain-15.3.rel1-x86_64-arm-none-linux-gnueabihf/bin/arm-none-linux-gnueabihf- \
  /home/pi/worktrees/ea-emb-linux/codex/uuf-milestones/sdk/bsp_imx/04-br-rtfs-integration/uuf/firmware/build.sh build \
  /home/pi/worktrees/ea-emb-linux/codex/uuf-milestones/sdk/bsp_imx/04-br-rtfs-integration/uuf/build/m1-r4-20261013
```

六个板级／ext4 对象交叉编译通过，原生板级命令和 ext4 检查通过；准确 JSB 故障注入已覆盖。运行证据见 `artifacts/2026-10-13-uuf-m1/collection.json`。

首轮云端 review 审阅 `b229061`，指出一项 P2：boot0 校验、分配或对齐失败后未恢复 user area。已统一修正相关退出路径，原生回归验证错误后恢复 user area 且未写入介质。

云端已完成 `52c0197` 的[第二轮 review](https://github.com/yceachan/ea-emb-linux/pull/1#issuecomment-6146457985)，未发现重大问题，原 P2 已关闭。实板证据门槛保持独立。

## M2 的实现与验证

CLI 提供 layout、pack、unpack、inspect、deploy、update 和 erase。MBR 是唯一几何来源，targets 仅描述角色／分区号／文件路径，启动描述与固件部署描述独立。实现说明与操作入口见 [uuf/README.md](../../../uuf/README.md)，执行及审阅边界见 [ADR-05](adr.md)。

完整归档可直接部署，打包时重建两个 ext4；独立更新不写 MBR，按实际 extlinux 与 root PARTUUID 核对角色。主机 dry-run 不访问板卡，正式操作两次确认并复核实际目标和暂存内容。CLI 与后续 GUI 共用参数验证、JSON Lines 事件和执行后端。

真实 M1 固件与 03 kernel／DTB／BusyBox rtfs 的制像、归档回环、原生 UUU 离线检查通过；修改一个分区的布局后，两张镜像 UUID 都更新。32 项主机／协议检查通过，覆盖组件容量、空盘、角色互换、确认后变化、错误停止和重复取消。rootfs 元数据保留经实际制像核对。

云端发现均已修正；复审中重复报告的 CRLF 字节计数问题按同一项处理。最后一项容量问题改为复用 pack 的 mkfs 参数，实测空文件系统开销再扩大布局；2 GiB rootfs 示例满足载荷和 64 MiB 预留量。扩展属性块和 kernel 目标路径父目录已计入载荷，10,000 个带 3 KiB 属性的目录与两个 90 层目标路径的实际制像均满足预留量；启动配置按实际 UTF-8 字节数计入容量，extlinux 同时按既有协议限制为最多 8 KiB，精确边界制像和多一字节拒绝通过；归档读取保留 CRLF 原始字节，防止文本换行归一化绕过上限；最新实现待云端复审。

Linux `/boot` 示例设备仅是集成输入，尚无本轮实板映射证据；持久写入、组件保留内容与冷启动仍待开发者验收。运行证据见 `artifacts/2026-10-15-uuf-32m/m2.json`。M3 保持未开始，待 M2 云端 review 与人工审阅后推进。

## 32 MiB 内存预算

开发者确认 DDR 为 512 MiB，并确定本轮完整文件窗口为 32 MiB。M1 完整构建通过，链接后的加载地址与配置一致；16 MiB heap 约束下，实际 ext4 写入器完成 32 MiB 大小载荷覆盖、读回和未选文件／所有权保留。M2 同步输入上限与固件配置核验，精确 32 MiB 接受、多一字节拒绝、旧 release 拒绝均通过。

内存决策见 [ADR-06](adr.md)，地址与执行边界见 [firmware/README.md](../../../uuf/firmware/README.md)。边界载荷不是可启动内核，实板解压、冷启动及写入仍待验收。M1 的 32 MiB 调整云端复审未发现重大问题，本轮待开发者人工审阅；运行证据见 `artifacts/2026-10-15-uuf-32m/m1.json`。
