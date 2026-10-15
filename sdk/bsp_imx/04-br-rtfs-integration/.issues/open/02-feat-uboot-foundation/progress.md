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

M1／M2／M3 已按 [route.md](route.md) 完成分阶段实现和主机验证，云端审阅未发现重大问题。2026-10-15，开发者授权将三个阶段交付整理到 `main`。实板行为由 R4 独立验收。

## 工作区

M1／M2 工作区：`/home/pi/worktrees/ea-emb-linux/codex/uuf-milestones`。

M3 工作区：`/home/pi/worktrees/ea-emb-linux/codex/uuf-gui`，基于 M2 的 `fdd8a7e` 开发。

需求基线：`codex/uuf-baseline`，提交 `f5598ee`；包含当前 issue 与失败实现参考。该分支承接本地 main 尚未发布的提交，阶段 PR 基于它审阅。

| 阶段 | 分支与 PR | 状态 |
|---|---|---|
| M1 U-Boot | `codex/uuf-uboot`，[PR #1](https://github.com/yceachan/ea-emb-linux/pull/1) | 完整构建与主机验证通过，云端复审未发现重大问题；开发者已授权进入 M2 |
| M2 host flasher | `codex/uuf-host-flasher`，[PR #2](https://github.com/yceachan/ea-emb-linux/pull/2) | CLI 与真实载荷集成通过，32 MiB 调整、32 项主机检查与真实载荷集成通过；云端复审未发现重大问题；开发者已授权进入 M3 |
| M3 GUI | `codex/uuf-gui`，[PR #3](https://github.com/yceachan/ea-emb-linux/pull/3) | 实现、主机与原生验证通过；云端审阅未发现重大问题；开发者已授权合入 main |

## M1 的实现与验证

迁入固定 U-Boot 板级输入，补齐 ROM USB／eMMC 启动分流、extlinux 和 3 秒打断。加入板端文件写入、固件范围保护、hash 门控和启动设置核验。实现说明与操作入口见 [firmware/README.md](../../../uuf/firmware/README.md)。

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

完整归档可直接部署，打包时重建两个 ext4；独立更新不写 MBR，按实际 extlinux 与 root PARTUUID 核对角色。主机 dry-run 不访问板卡，正式操作两次确认并复核实际目标和暂存内容。CLI 与 GUI 共用参数验证、JSON Lines 事件和执行后端。

真实 M1 固件与 03 kernel／DTB／BusyBox rtfs 的制像、归档回环、原生 UUU 离线检查通过；修改一个分区的布局后，两张镜像 UUID 都更新。32 项主机／协议检查通过，覆盖组件容量、空盘、角色互换、确认后变化、错误停止和重复取消。rootfs 元数据保留经实际制像核对。

容量估算已覆盖 ext4 元数据、目录扩展属性、目标父目录和实际 extlinux 文本。extlinux 保持既有 8 KiB 导出上限，按原始 UTF-8 字节校验，CRLF 不做换行归一化。

云端发现均已修正，全部审阅讨论已解决。最新实现 `dc5d986` 的[最终复审](https://github.com/yceachan/ea-emb-linux/pull/2#issuecomment-6190348756)未发现重大问题。本轮设计与实现已收口，交开发者人工审阅。

Linux `/boot` 示例设备仅是集成输入，尚无本轮实板映射证据；持久写入、组件保留内容与冷启动仍待开发者验收。运行证据见 `artifacts/2026-10-15-uuf-32m/m2.json`。2026-10-15，开发者指示开始阶段三，M3 从该基线推进。

## 32 MiB 内存预算

开发者确认 DDR 为 512 MiB，并确定本轮完整文件窗口为 32 MiB。M1 完整构建通过，链接后的加载地址与配置一致；16 MiB heap 约束下，实际 ext4 写入器完成 32 MiB 大小载荷覆盖、读回和未选文件／所有权保留。M2 同步输入上限与固件配置核验，精确 32 MiB 接受、多一字节拒绝、旧 release 拒绝均通过。

内存决策见 [ADR-06](adr.md)，地址与执行边界见 [firmware/README.md](../../../uuf/firmware/README.md)。边界载荷不是可启动内核，实板解压、冷启动及写入仍待验收。M1 的 32 MiB 调整云端复审未发现重大问题，本轮已纳入主线集成；运行证据见 `artifacts/2026-10-15-uuf-32m/m1.json`。

## M3 的实现与验证

Tauri／React GUI 提供烧录、镜像准备、设备信息三页，共用 M2 Python RPC。新增的 `mbr` 编辑和 `describe` 归档查询也由 CLI 调用；分区几何仍以 MBR 为唯一事实源。设计见 [ADR-07](adr.md)，使用与构建见 [GUI README](../../../uuf/gui/README.md)。

确认界面直接展示后端计划，输入在任务期间锁定。主机计划确认后才能下载 RAM loader，真实设备写入确认要求核对 CID。取消等待子进程退出和输出管道关闭后才解锁，结果事件不会提前解除锁定；旧任务事件不能覆盖新任务。

前端交互、MBR 编辑、Rust 桥接与既有主机检查通过。原生 Tauri 交互覆盖真实文件选择、确认、故障停止、取消清理，以及真实载荷制像、布局编辑和归档回环。真实 UUU 仅运行离线检查，正式流程使用协议模拟器；实板写入与冷启动仍待验收。运行证据见 `artifacts/2026-10-15-uuf-m3/collection.json`。

RPM 调试包构建通过，解包后的程序在独立目录完成同一原生验证流程。云端完成 `fac103a` 的[审阅](https://github.com/yceachan/ea-emb-linux/pull/3#issuecomment-6191510296)，未发现重大问题。开发者已授权将三个阶段交付合入 `main`，后续实板验收由 R4 推进。
