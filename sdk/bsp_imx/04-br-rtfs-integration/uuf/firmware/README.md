---
title: uuf · M1 板级 U-Boot
tags: [uuf, U-Boot, firmware]
note_types: document
created: 2026-10-13
updated: 2026-10-13
template: doc
lang: zh

---

# uuf · M1 板级 U-Boot

本固件同时承担 ROM USB 下载后的 RAM loader 和 eMMC boot0 中的产品 U-Boot。M1 为后续 host flasher 提供可检查的板端操作；需求以 [issue 02](../../.issues/open/02-feat-uboot-foundation/issue.md) 为准。

## 启动行为

固定输入来自 02 板卡基线：`base-revision` 指定上游提交，overlay 维护 DDR、UART1、USB 与 USDHC2，注册补丁把板卡加入 U-Boot 构建。`board_late_init()` 检测 ROM USB 启动后进入 fastboot。eMMC 启动保留 3 秒控制台打断窗口，再从活动分区的 `/extlinux/extlinux.conf` 引导 kernel／DTB。采用 RAM 环境，启动项由 extlinux 文件维护。

产品固件写入 boot0 的字节偏移为 `0x400`，部署描述见 `target.json`。user area 的 MBR 与启动文件由 M2 准备；固件不把分区角色和几何固化到配置中。extlinux 扫描属于启动流程，主机更新目标的消歧由 M2 负责。

## 板端操作

UUU 通过 `FB: ucmd uuf ...` 调用板级命令。数字参数使用十六进制，起点按 512 字节 LBA 表示，长度按字节表示。`hw=0` 表示 user area，`hw=1` 表示 boot0。

| 命令 | 行为 |
|---|---|
| `info`、`matchcid CID` | 返回容量、CID、擦除粒度、启动设置；复核确认的设备身份 |
| `export hw start bytes` | 导出不超过 8192 字节的原始信息，支持空盘 MBR 读取 |
| `locate part`、`exportfile part path` | 定位 extlinux 或读取文件；part 为 0 时发现候选，多候选拒绝 |
| `writable part path` | 只读检查现有目标文件是否满足写入器限制 |
| `writefile part path bytes sha256` | 校验下载长度和 hash，覆盖文件后读回长度和 hash |
| `fw hw start bytes sha256` | 限定 boot0 起点 LBA 2；hash 相同免写，不同则写入并核验 |
| `bootconf ack partition` | 独立核对并设置 EXT_CSD 启动区域 |
| `verify hw start bytes sha256`、`file part path bytes sha256` | 核对介质范围或文件的 SHA-256 |
| `erase hw start bytes` | 按真实擦除粒度检查范围，拒绝扩大范围，写后核验擦除值 |
| `save`、`filesave`、`keep` | 保存和比较未选范围或文件的摘要，用于内容保留核验 |

固件命令保留末扇区的未使用字节，不先扩大范围擦除。内存 hash 和介质 hash 都要匹配；MMC 短读、短写与核验失败向 UUU 返回错误。摘要快照不提供数据回滚。

## ext4 文件更新边界

`ext4-io.patch` 补齐短 I/O 错误传播、非整扇区写入、完整 inode 读取、覆盖后的所有权保留和 journal 清理错误返回。journal 未成功清理时保留 RECOVER。补丁针对固定 revision，更新上游后必须重新核对。

kernel 分区使用 4096 字节块和干净的 journal。制像需关闭写入器不支持的 `metadata_csum`、`64bit`、`orphan_file`、`dir_index`、`flex_bg`，不能带入主机 xattr。板端在写入器初始化前拒绝缺失或不干净的 journal 和不支持的特性。仅覆盖现有普通单链接文件；符号链接、硬链接、目标 xattr／ACL、不支持的 inode flags 和带索引块的 extent 树会被拒绝。写入不提供原子替换或断电回滚。

fastboot buffer 位于 `0x82000000`，容量 16 MiB；heap 为 16 MiB。kernel、DTB 和启动配置的加载地址分别为 `0x82000000`、`0x83000000`、`0x84000000`。输入和文件系统必须符合这些真实限制。

## 构建与主机验证

从任意 CWD 提供绝对路径。`BUILD` 必须为新目录；配置或板级输入变化后重新 configure。

```sh
FIRMWARE=/absolute/path/to/uuf/firmware
BUILD=/absolute/path/to/new-uboot-build
export UBOOT_SOURCE=/absolute/path/to/uboot-git-repository
export CROSS_COMPILE=/absolute/path/to/toolchain/bin/arm-none-linux-gnueabihf-
"$FIRMWARE/build.sh" configure "$BUILD"
"$FIRMWARE/build.sh" check "$BUILD"
```

`check` 编译板级与 ext4 对象。完整 SDK 构建由开发者执行，默认 `-j12`：

```sh
"$FIRMWARE/build.sh" build "$BUILD"
```

`release/` 保存固件、配置、固定 revision、输入及源码清单和 hash。构建入口拒绝使用被手工改变的源码或配置。

主机原生验证使用普通文件与内存模拟介质，执行真实板端及 U-Boot ext4 源码，不访问板卡：

```sh
python3 "$FIRMWARE/tests/check_board.py" --output "$BUILD/board-check"
python3 "$FIRMWARE/tests/native/verify.py" --source "$BUILD/src" \
  --kernel /absolute/path/to/03/zImage --dtb /absolute/path/to/03/board.dtb \
  --output "$BUILD/ext4-check"
```

测试依赖主机 C 编译器、OpenSSL 开发库、e2fsprogs、dtc 和 fdtget。native harness 限制写入器 heap 为 16 MiB，检查原始 kernel／DTB 覆盖、未选文件和所有权、文件系统一致性，以及短 I/O 和 journal 错误。JSB 读取故障在真实 journal superblock 数据读取前注入，避免按调用次数误认注入位置。

## 阶段验收

主机原生验证和对象编译只证明对应代码路径。完整固件链接、ROM USB 自动 fastboot、eMMC 冷启动、3 秒打断与板端文件更新分别记录证据。实板写入由开发者执行；后续 M2 提供经过 dry-run 与二次确认的主机入口。

M1 验证记录位于 issue 的 `artifacts/2026-10-13-uuf-m1/collection.json`；阶段状态与 PR 见 [progress.md](../../.issues/open/02-feat-uboot-foundation/progress.md)。
