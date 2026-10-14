---
title: uuf · 三阶段开发进度
tags: [uuf, milestone, review]
note_types: document
created: 2026-10-13
updated: 2026-10-13
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
| M2 host flasher | `codex/uuf-host-flasher`，独立 PR 待创建 | 开发中 |
| M3 GUI | 待 M2 人工审阅后创建 | 未开始 |

## M1 的实现与验证

迁入固定 U-Boot 板级输入、ROM USB／eMMC 启动分流、extlinux 和 3 秒打断，以及板端文件写入、固件范围保护、hash 门控和启动设置核验。实现说明与操作入口见 [firmware/README.md](../../../uuf/firmware/README.md)。

原生验证直接编译生产板级命令和配置后的 U-Boot ext4 源码，使用内存或普通文件介质。补齐 journal superblock 数据读取的准确故障注入，并将文件系统特性／journal 状态检查前移到写入器初始化之前。拒绝 unlink 写入器无法释放索引块的 extent 树。

2026-10-13，开发者允许本 session 执行 SDK 构建集成，并指示构建 U-Boot 后进入 host flasher CLI。固定输入的完整 U-Boot 构建已通过，release 生成 DCD 镜像及可核对的六项文件清单。ROM USB 自动 fastboot、eMMC 冷启动、3 秒打断及实板文件更新仍待验收。

当前已配置并完成对象检查的目录可用于完整链接：

```sh
env CROSS_COMPILE=/home/pi/ea-emb-linux/sdk/vendor_mainline/toolchains/arm-gnu-toolchain-15.3.rel1-x86_64-arm-none-linux-gnueabihf/bin/arm-none-linux-gnueabihf- \
  /home/pi/worktrees/ea-emb-linux/codex/uuf-milestones/sdk/bsp_imx/04-br-rtfs-integration/uuf/firmware/build.sh build \
  /home/pi/worktrees/ea-emb-linux/codex/uuf-milestones/sdk/bsp_imx/04-br-rtfs-integration/uuf/build/m1-r4-20261013
```

六个板级／ext4 对象交叉编译通过，原生板级命令和 ext4 检查通过；准确 JSB 故障注入已覆盖。运行证据见 `artifacts/2026-10-13-uuf-m1/collection.json`。

首轮云端 review 审阅 `b229061`，指出一项 P2：boot0 校验、分配或对齐失败后未恢复 user area。已统一修正相关退出路径，原生回归验证错误后恢复 user area 且未写入介质。

云端已完成 `52c0197` 的[第二轮 review](https://github.com/yceachan/ea-emb-linux/pull/1#issuecomment-6146457985)，未发现重大问题，原 P2 已关闭。实板证据门槛保持独立。
