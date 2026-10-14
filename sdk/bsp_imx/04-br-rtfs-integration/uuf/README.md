---
title: uuf · host flasher CLI
tags: [uuf, UUU, MBR, Sparse, ext4]
note_types: document
created: 2026-10-13
updated: 2026-10-15
template: doc
lang: zh

---

# uuf · host flasher CLI

`uuf` 为当前 i.MX6ULL 板卡准备镜像、校验归档、形成计划并编排 UUU。完整系统直接消费归档文件；独立更新消费原始 kernel／DTB 或 rtfs Sparse。CLI 与后续 GUI 共用后端，设备信息和写入计划始终由实际探测与明确目标共同确定。需求与验收以 [issue 02](../.issues/open/02-feat-uboot-foundation/issue.md) 为准，阶段状态见 [progress.md](../.issues/open/02-feat-uboot-foundation/progress.md)。

## 1 · 数据来源与支持范围

| 对象 | 职责与来源 |
|---|---|
| 最终 MBR | 唯一分区几何来源：signature、表项、起点、长度、类型和活动标志 |
| `targets.json` | 当前板卡、kernel／DTB 的分区号和目标路径、rtfs 分区号；不含几何 |
| `boot.json` | LABEL、kernel／DTB 路径和 APPEND；制像时核对或补入 MBR 对应的 root PARTUUID |
| 固件部署描述 | boot0 范围与启动设置，默认来自 [firmware/target.json](firmware/target.json)；与布局分开 |
| 归档清单 | 组件载荷文件和目标映射；文件校验由 SHA256SUMS 提供，不再保存分区起点和容量 |
| 实际探测 | CID、user／boot0 容量、擦除粒度、启动设置及原始 MBR；基础探测支持空盘 |

完整系统归档包含 MBR、产品 U-Boot 及构建记录、两张分区 Sparse、原始 kernel／DTB、extlinux 和清单。部署在任务目录中解包并校验，用户无需额外 profile 或手工解包。

MBR 使用两个 Linux 主分区，只有映射的 kernel 分区允许带活动标志。kernel、DTB 与 `/extlinux/extlinux.conf` 位于 kernel 分区。源文件名不决定目标文件名。Linux 根分区通过 MBR PARTUUID 引用，Linux 的 MMC 设备号不能从 U-Boot MMC 1 推断。

kernel 输入为不超过 32 MiB 的 ARM zImage，DTB 必须属于当前板卡。Sparse 支持 v1.0、4096 字节块、RAW／FILL／DONT_CARE、无 CRC 扩展。kernel ext4 使用 M1 写入器支持的特性与干净 journal；实际文件写入还会检查目标 inode，限制见 [firmware/README.md](firmware/README.md)。

## 2 · 准备布局与完整归档

主机依赖 Python 3.12+、UUU、e2fsprogs、fakeroot、dtc 和 fdtget。主机路径均由参数或环境提供，可从任意 CWD 执行。固件输入使用 M1 `build.sh` 生成的 `release/`。

```sh
UUF=/absolute/path/to/uuf/uuf
FW=/absolute/path/to/uboot-build/release
KERNEL=/absolute/path/to/zImage
DTB=/absolute/path/to/board.dtb
ROOTFS=/absolute/path/to/rootfs.tar.gz
WORK=/absolute/path/to/new-preparation
UUU=/absolute/path/to/uuu
mkdir "$WORK"
"$UUF" layout --kernel "$KERNEL" --dtb "$DTB" --rootfs "$ROOTFS" \
  --kernel-path /zImage --dtb-path /board.dtb --output "$WORK/layout"
```

默认几何按真实载荷、文件数量、文件系统开销和预留量计算。kernel 预留 32 MiB、rtfs 预留 64 MiB，可用字节参数 `--kernel-reserve`／`--rtfs-reserve` 调整；打包会核对实际空闲空间。`--disk-sectors` 可用实测容量提前限制布局，省略时仍须在 loader 启动后复核设备容量。

layout 的输出目录须在目录 rootfs 输入树之外。layout 生成 `mbr.bin`、独立 `targets.json` 和 `boot.json`。可使用外部工具或后续 GUI 编辑最终 MBR；打包读取该文件，不根据第二份 JSON 几何重新生成。映射示例：

```json
{"board":"100ask-imx6ull-pro",
 "kernel":{"partition":1,"path":"/zImage"},
 "dtb":{"partition":1,"path":"/board.dtb"},
 "rtfs":{"partition":2}}
```

```sh
"$UUF" pack --firmware "$FW" --kernel "$KERNEL" --dtb "$DTB" --rootfs "$ROOTFS" \
  --mbr "$WORK/layout/mbr.bin" --targets "$WORK/layout/targets.json" \
  --boot "$WORK/layout/boot.json" --output "$WORK/bundle" --archive "$WORK/system.tar.gz"
"$UUF" unpack --archive "$WORK/system.tar.gz" --output "$WORK/unpacked"
```

bundle 输出目录和归档文件均须选择在 rootfs 与固件输入树之外，归档文件还须位于 bundle 目录外。固件仅复制已验证的清单文件与 SHA256SUMS，清单外条目不进入归档。pack 每次根据最终 MBR 新建 kernel、rtfs 两个 ext4，再按分配块制作 Sparse。即使只修改一个分区的几何，也重建两者。较大的设备保留归档几何；容量不足时拒绝。DONT_CARE 可保留介质旧字节，逻辑重建不要求物理擦除。

rootfs 输入为目录树或 tar。目录树使用其现有 UID／GID、mode、常规 hardlink 与扩展属性；tar 保留 UID／GID、mode、常规 hardlink、符号链接及字符／块设备节点。含扩展属性／ACL 的 tar 会拒绝，需提供保留属性的目录树。特殊文件 hardlink 不受支持。提取不经过链接父目录，绝对符号链接作为目标系统数据保存。

首轮 03 BusyBox 需要准备 kernel 分区的 `/boot` 挂载。只有在实际 Linux 设备号已核对后，向 pack 添加 `--linux-boot-device /dev/mmcblkNp1`；分区号须与 targets 一致。该入口只修改 03 基线 rcS 并新增或替换 fstab 的 `/boot` 条目，保留其他挂载与注释；其他系统的挂载由其 rootfs 输入维护。镜像内旧 `/boot` 内容在挂载后被 kernel 分区覆盖，工具不擅自删除源目录数据。

## 3 · 主机预检、实际目标与执行

以下为写入任务的执行流程。

```flow
暂存及主机离线预检 -> {dry-run?}
{dry-run?} -> 主机检查结果: 是
{dry-run?} -> 确认主机计划: 否
确认主机计划 -> RAM loader 与只读探测
RAM loader 与只读探测 -> 范围计划与离线解析
范围计划与离线解析 -> 确认实际目标
确认实际目标 -> 重探并校验输入: 确认
确认实际目标 -> 停止与进程清理: 取消
重探并校验输入 -> 写入与读回核验
写入与读回核验 -> 待冷启动验收: 成功
写入与读回核验 -> 停止与进程清理: 错误或取消
```

```sh
"$UUF" deploy --archive "$WORK/system.tar.gz" --uuu "$UUU" --dry-run
"$UUF" inspect --firmware "$FW" --uuu "$UUU" --log-dir "$WORK/inspect"
```

dry-run 只校验主机输入、计划与可确定的 UUU 脚本，不枚举 USB、不下载 loader、不访问板卡。计划明确列出尚待真实设备复核的项目。基础 inspect 不依赖产品分区表或 extlinux；明确使用 `--with-boot` 时才要求启动路径信息。

正式写入由开发者执行。先运行 dry-run，再移除该参数；程序仍重新预检并要求两次确认：

- 输入 `CONTINUE` 后才枚举 ROM 设备、下载 RAM loader，并读取实际设备。多块设备须用 `--usb-path` 明确选择。
- 检查真实 CID、布局和范围，输入 `WRITE` 加 CID 末 8 位后才写入。确认后重探设备／布局并核对暂存 hash，变化即拒绝；写入脚本在任何持久写入前再次按已确认的长度和 SHA-256 核对 extlinux。

任务默认存放到 `~/uuf-logs/`，可通过 `--log-dir` 指定新目录或 `UUF_LOG_ROOT` 指定根目录。保存计划、设备快照、UUU 脚本和日志。UUU 入口可通过 `--uuu` 或 `UUF_UUU` 指定；在切换任务目录前固定其绝对路径，保持启动器路径，不能把 Snap 的 `uuu` 符号链接替换为 `snap` 可执行文件。Snap 自身的文件访问限制仍由运行环境决定。

完整系统 deploy 包含 U-Boot、MBR、两个分区镜像；部分组件使用 update。GUI 的选择必须对应相同后端操作，完整部署不接受“排除 U-Boot”的无效选项。

## 4 · 独立更新与明确擦除

```sh
"$UUF" update --firmware "$FW" --uboot --uuu "$UUU" --dry-run
"$UUF" update --firmware "$FW" --targets "$WORK/layout/targets.json" \
  --kernel "$KERNEL" --dtb "$DTB" --uuu "$UUU" --dry-run
"$UUF" update --firmware "$FW" --targets "$WORK/layout/targets.json" \
  --rtfs "$WORK/unpacked/rtfs.sparse" --uuu "$UUU" --dry-run
```

update 可组合 U-Boot、kernel、DTB 和 rtfs，只操作提供的组件。固件单独更新不依赖系统镜像或有效 MBR。kernel／DTB 使用原始文件定向覆盖，保留 extlinux 和其他文件；rtfs 使用完整分区 Sparse。它们不修改 MBR。

实际 extlinux 分区、所选 LABEL 中的文件路径和 root PARTUUID共同确定当前角色，输入映射必须与其一致。多候选需指定 `--kernel-part` 或 `--label`，不能仅比较几何后相信 kernel／rtfs 名称。运行系统独立修改 APPEND 或 DEFAULT 后，只要所选目标仍一致，文件更新不会要求重建分区。

独立操作可给出 `--expected-mbr FILE` 进行离线容量检查和实时字节核对；该文件不会写入。未给出时，部分范围和完整 flash 脚本在实际 MBR 探测后确定，dry-run 会明确标为待检查。

```sh
"$UUF" erase --firmware "$FW" --targets "$WORK/layout/targets.json" \
  --region rtfs --expected-mbr "$WORK/layout/mbr.bin" --uuu "$UUU" --dry-run
"$UUF" erase --firmware "$FW" --region firmware --offset 0 --bytes 0x100000 \
  --uuu "$UUU" --dry-run
```

kernel／rtfs 擦除仅面向已核对角色的完整分区；固件擦除需明确 boot0 字节范围。实际容量和 erase group 不满足计划时拒绝，不扩大范围。大分区按板端单条命令的 32 位长度与实际擦除粒度拆分，保持完整目标范围。示例范围只是显式输入，不能代替设备粒度检查和人工确认。修改布局应重新 pack 并部署包含两个新 ext4 的归档，不能单独写新 MBR。

## 5 · 核验、取消与后端接口

计划分别记录源容器字节、Sparse 逻辑长度、分区容量和有效写入字节。RAW／FILL 全部写入并按范围核验，包括有意义的零；DONT_CARE 跳过块以写前摘要保护。未选分区和已知未选启动文件按计划保存、比较摘要；未知额外文件的保留由 M1 文件系统实现及实板验收覆盖，不能据此声称每个额外文件都已逐一 hash。

固件内容 hash 相同则免写，启动设置仍独立核验。错误、断连或比较失败停止后续操作，已写内容不自动回滚。取消处理只接收一次中断，后续信号不会打断清理；任务退出前等待 UUU 进程组终止。嵌套制像工具留在 fakeroot 任务组内，避免取消时遗留写入子进程。

后续 GUI 调用 `uuf rpc`：输入一行操作 JSON，stdout 返回 JSON Lines 事件。操作字段与 CLI 相同，未知字段和不正确类型会拒绝，即使字段值为 false。后端通过 `confirmation` 事件给出阶段、计划和随机 token，调用者以一行 `{"confirm":"token"}` 回复。日志、计划、目标、错误和结果使用同一通道；不建立第二套 GUI 烧录逻辑。

## 6 · 主机验证与实板门槛

复现完整主机集成检查：

```sh
python3 /absolute/path/to/uuf/tests/integrate.py --firmware "$FW" \
  --kernel "$KERNEL" --dtb "$DTB" --rootfs "$ROOTFS" --uuu "$UUU" \
  --linux-boot-device /dev/mmcblkNp1 --output "$WORK/integration"
```

检查真实载荷制像与归档直读、解包回环、修改布局后双 ext4 重建、UID／GID／hardlink／设备节点保留，并运行协议模拟检查。协议模拟覆盖范围计划、空盘、角色互换、目标变化、错误停止及重复取消，不代替实板。

运行证据见 issue 02 的 `artifacts/2026-10-13-uuf-m2/collection.json`。板端持久写入、实际 Linux `/boot` 设备、组件保留内容和冷启动仍由开发者验收，成功的主机结果保留 `cold_boot: pending-developer-validation`。
