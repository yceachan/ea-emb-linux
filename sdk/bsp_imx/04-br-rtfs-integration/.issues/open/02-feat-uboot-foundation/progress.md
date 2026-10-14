---
title: uuf · 三阶段开发进度
tags: [uuf, milestone, review]
note_types: document
created: 2026-10-13
updated: 2026-10-14
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
| M2 host flasher | `codex/uuf-host-flasher`，[PR #2](https://github.com/yceachan/ea-emb-linux/pull/2) | CLI 与真实载荷集成通过，首轮云端发现已修正，待复审与人工审阅 |
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

2026-10-14 中断恢复复核：当前分支为 `codex/uuf-host-flasher`，继承已发布的 M1 `d15b358`。M1 release 清单、M2 运行证据与当前 CLI 源码 hash 全部一致。阶段二的执行边界已收敛到 [ADR-05](adr.md)，实现以 `4f4374b` 发布到独立 PR #2，base 为 `codex/uuf-uboot`。

CLI 提供 layout、pack、unpack、inspect、deploy、update 和 erase。MBR 是唯一几何来源，targets 仅描述角色／分区号／文件路径，启动描述与固件部署描述独立。实现说明和操作入口见 [uuf/README.md](../../../uuf/README.md)。

完整归档可直接部署，打包时重建两个 ext4；独立更新不写 MBR，按实际 extlinux 与 root PARTUUID 核对角色。主机 dry-run 不访问板卡，正式操作两次确认并复核实际目标和暂存内容。CLI 与后续 GUI 共用参数验证、JSON Lines 事件和执行后端。

真实 M1 固件与 03 kernel／DTB／BusyBox rtfs 的制像、归档回环、UUU 离线检查通过；修改一个分区的布局后，两张镜像 UUID 都更新。24 项主机／协议检查通过，覆盖空盘、角色互换、容量误报、确认后变化、错误停止和重复取消。rootfs 的所有权、hardlink、符号链接和设备节点通过实际制像检查；目录输入的真实所有权与扩展属性也已核对。

Linux `/boot` 示例设备仅是集成输入，尚无本轮实板映射证据；持久写入、组件保留内容与冷启动仍待开发者验收。运行证据见 `artifacts/2026-10-13-uuf-m2/collection.json`。M3 保持未开始，待 M2 云端 review 与人工审阅后推进。

首轮云端 review 返回一项 P1 与两项 P2，均已修正：只允许 kernel 活动标志；在同一写入脚本中核对已确认 extlinux 后才允许写入；准备 `/boot` 时保留 fstab 的其他条目与注释。新增启动配置竞态和活动标志检查，实际制像核对 fstab 的数据分区／swap 条目保留，待云端复审。

第二轮云端 review 的一项 P2 已修正：UUU 查找结果在切换任务目录前固定为绝对路径，保留符号链接；参数、环境变量和相对 PATH 三种入口均覆盖，测试临时目录不依赖仓库内 build 路径。当前 22 项检查与原生 UUU 离线集成通过，待最终复审。

第三轮云端 review 的大分区擦除 P2 已修正：保持整分区计划，命令按板端 32 位长度与实际 erase group 拆分，不扩大或遗漏范围。5 GiB 分区的协议检查验证连续、对齐与总长度，当前 23 项检查及真实载荷集成通过，待云端复审。

第四轮云端 review 的输出路径 P2 已修正：打包创建文件前拒绝输出位于 rootfs 或固件输入目录内部，防止输入污染与递归复制。两种目录均检查拒绝后没有创建输出；当前 24 项检查与真实载荷集成通过，待云端复审。

第五轮云端 review 的两项 P2 已修正：归档目标与 bundle 输出同样在创建前检查；固件仅复制已验证清单文件，清单须为普通文件。真实制像确认清单外日志与外部符号链接未进入归档，输入树内的归档路径提前拒绝；24 项检查继续通过。
