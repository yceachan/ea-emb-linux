---
title: 04 U-Boot 与单份整盘镜像烧录流程
tags: [U-Boot, UUU, i.MX6ULL, BusyBox, eMMC]
note_types: document
created: 2026-10-10
updated: 2026-10-10

---


# 04 U-Boot 与单份整盘镜像烧录流程

> [!WARNING]
> 本页保留的是此前 FAT32/BusyBox 专用原型的操作记录，不是最新确认的通用 MBR/ext4 基础层接口。当前需求与待讨论项以 [U-Boot 专章](../.issues/open/02-feat-uboot-foundation/issue.md) 为准；下面命令不得作为新范围已实现或已验收的依据。新接口确认及实现后再更新完整操作流程。

本页是完整操作流程：构建 U-Boot → 准备 03 BusyBox 验收镜像 → 绑定固件生成下载包 → `--all` 预检 → `--all` 正式烧录 → eMMC 冷启动与串口验收。**整盘阶段只写一份 `system.sparse.img`，不分别烧录 kernel、DTB、rootfs。**完整构建和真实板卡写入由开发者执行。

## 1. 统一路径，只定义一次

在同一个主机 shell 中设置下面变量，后续命令全部使用它们：

```sh
root=/home/pi/ea-emb-linux
bsp="$root/sdk/bsp_imx/04-br-rtfs-integration"
u="$bsp/uboot"
work="$bsp/build/uboot"
fw="$work/firmware/out"
payload="$work/busybox-validation/payload"
pkg="$work/busybox-validation/download"
```

| 变量 | 含义 | 使用者 |
|---|---|---|
| `$u` | 本轮源码、构建/打包/烧录工具、测试与文档 | 所有入口 |
| `$work` | 仅 U-Boot 本轮的构建根，不是固件输入目录 | 主机输出 |
| `$fw` | U-Boot **构建产物目录**，包含 .imx、.config 和 SHA256SUMS | `--firmware "$fw"` |
| `$payload` | 03 BusyBox 适配后的真实 rootfs、kernel/DTB 与验收镜像 | 制作最终下载包 |
| `$pkg` | **最终烧录包目录**，含固件、system.sparse.img 与清单 | `--package "$pkg"` |

`out` 是 `$fw` 路径的最后一层，不是另一个独立工作区；烧录整盘时输入的是 `$pkg`，不是 `$fw` 或 `$work`。本轮实现均在 `$u`，不在 04 根目录放脚本、布局或配置。

## 2. 构建当前 U-Boot

```sh
"$u/build.sh" configure
# 完整构建由开发者执行，固定 -j12：
"$u/build.sh" build
(cd "$fw" && sha256sum --check --strict SHA256SUMS)
```

首次 configure 要求 `$work/firmware` 尚不存在。若已有旧快照或输入发生变化，先把该目录移到备份位置，再 configure/build；不要手工重算旧输入清单绕过检查。继续使用 `profile/prebuilt.env` 的 ARM GNU 工具链，固定 revision、overlay 和 patch，不改共享上游源码。

产物必须是当前输入对应的 `$fw/u-boot-dtb.imx`。自身 hash 通过的旧 .imx 不等于当前固件；本次发现的旧产物输入记录不匹配，不能拿它完成本轮验收。代理不执行这一步完整构建。

## 3. 用 03 BusyBox 基线准备验收镜像

03 的归档已固定 hash，kernel/DTB/BusyBox 不重新编译，也不修改 03 原文件。先只读预检，再在主机生成新副本：

```sh
"$u/busybox-validation/prepare.py" --dry-run
"$u/busybox-validation/prepare.py" --output "$payload"
(cd "$payload" && sha256sum --check --strict SHA256SUMS)
```

本次已生成 `$payload`；重复制作必须使用新目录并同步修改 `payload` 变量。输出包含 p1 FAT32、p2 ext4、`system.raw.img` 和 `system.sparse.img`，但尚未绑定当前 U-Boot，**不能直接把这个目录传给 flash.py**。

适配采用当前布局：p1 从 LBA 2048 开始、128 MiB FAT32，根目录保存 zImage、板级 DTB、extlinux/extlinux.conf；p2 从 LBA 264192 开始、2 GiB ext4。将 03 原 `/boot` 的启动文件移到 p1，重建匹配容量的 p2；保留 BusyBox/init、kernel/DTB 和初始化基线，并加入只读验收脚本。移除 p2 中旧 `/boot` 副本，避免用未被 U-Boot 加载的重复文件冒充验证。无需 Linux VFAT 支持，后续直接核验实际 p1 块设备。

这是 **U-Boot 板级验收用 BusyBox 系统**，不是最终 BR/systemd 系统。主机镜像检查通过不表示板级验收已通过。

## 4. 将验收载荷与当前固件绑定成最终烧录包

```sh
"$u/package.py" \
  --firmware "$fw" \
  --kernel "$payload/zImage" \
  --dtb "$payload/imx6ull-100ask-pro.dtb" \
  --rootfs "$payload/rootfs.ext4" \
  --output "$pkg"
(cd "$pkg" && sha256sum --check --strict SHA256SUMS)
```

`$pkg` 必须尚不存在。打包核验当前固件身份、rootfs、分区表、启动文件与 Sparse 有效块，再制作最终镜像。最终 `$pkg/boot.fat` 可能与准备阶段的 FAT 元数据不同；**板上核验必须使用最终 `$pkg/boot.fat` 的 hash**。

| 最终包文件 | 整盘操作中的用途 |
|---|---|
| `loader.imx` | ROM 下载到 RAM，自动进入 fastboot |
| `system.sparse.img` | **唯一整盘烧录镜像**：包含 MBR、p1 kernel/DTB/启动配置和 p2 rootfs |
| `product.imx` | 另写 eMMC boot0 的产品 U-Boot，与 loader 绑定同一产物 |
| `system.raw.img`、`boot.fat` | 主机查验、生成及板上读回比较，不直接作为 --all 的下载文件 |
| 独立 kernel/DTB、`rootfs.sparse.img` | 预检/后续独立更新输入；**--all 不分别发送它们** |
| `layout.json`、固件记录、`SHA256SUMS` | 预检和写入范围检查 |

Sparse 只跳过 ext4 位图证明的空闲块及留白；已分配块中的零值使用 RAW/FILL。DONT_CARE 保留介质旧内容，不是安全擦除。镜像统计不等同实测 USB 传输量。

## 5. `--all` 单份整盘镜像：预检与正式烧录

### 5.1 主机预检，不需要接板

```sh
"$u/flash.py" --all --package "$pkg" --dry-run
```

入口检查整个最终包、固件身份、实际镜像结构和有效块，生成本次 task.uuu，再执行真实 UUU -dry。不枚举 USB、不 RAM 下载、不写板。`--all` 与位置操作 `all` 等价，只写一种，不同时写两个。

### 5.2 正式烧录：开发者确认后才写板

**该操作覆盖原系统分区表及系统有效块，并更新 boot0；首次建立新布局不是无损迁移。**将板卡设置为 ROM USB 下载模式，连接正确的 OTG 下载口，再在交互终端执行：

```sh
log="$u/artifacts/busybox-all-$(date +%Y%m%d-%H%M%S)"
"$u/flash.py" --all --package "$pkg" --log-dir "$log"
```

正式入口也会先重新执行相同主机预检。然后展示写入范围，识别 ROM USB 路径，要求输入完整 `WRITE <USB路径>`。多块板时加 `--usb-path 3:1` 等显式选择；确认后重查快照与目标，用 -m 固定该路径。没有 --yes 或无人值守绕过选项。

正式操作按以下顺序执行，无需手工向串口输入 fastboot：

1. ROM SDP 将 loader.imx 下载到 RAM；loader 自动进入 fastboot，USB 重新枚举。
2. 检查实际 eMMC/boot0 容量，执行一次 `FB: flash all system.sparse.img`。
3. 检查新 MBR/p1/p2 布局，逐段读取实际写入块并比较 SHA-256。
4. 执行 `FB: flash bootloader product.imx`，写 boot0 字节 0x400 起的镜像范围并读回比较。
5. 设置 `mmc partconf 1 1 1 0`，读回 EXT_CSD 的启动设置。
6. FB: Done 结束主机任务；板端仍在 fastboot，不自动重启。

失败会停止后续步骤，不自动回滚。退出码、错误文本与每条命令的 Okay 记录全部通过才生成 `$log/result.json`。默认 ROM 等待 30 秒、阶段切换 60 秒、总时限 3600 秒，可用 --wait/--stage-wait/--timeout 修改。

## 6. 冷启动与板级验收证据

烧录成功后，先连接串口记录，再由开发者切回 eMMC 启动模式、断电重新上电。可复用 02 的串口记录工具；这里仅用 console 模式，不使用 02 的固件或烧录入口：

```sh
coldlog="$u/artifacts/busybox-coldboot-$(date +%Y%m%d-%H%M%S)"
"$root/sdk/bsp_imx/02-uboot-porting/uboot.py" console \
  --serial /dev/ttyACM0 --baudrate 1500000 --log-dir "$coldlog"
```

按实际串口修改 --serial。日志需覆盖新 U-Boot 板名和 eMMC 启动路径、无需手工 boot 命令的 extlinux 加载、Linux 启动以及 BusyBox shell。

在主机计算**最终包**的 p1 hash，并打印要粘贴到板端 shell 的只读命令：

```sh
boot_sha=$(sha256sum "$pkg/boot.fat" | awk '{print $1}')
printf '/sbin/verify-uboot-busybox %s\n' "$boot_sha"
```

在板端执行打印出来的命令。它只读核验 kernel release、PID 1、BusyBox ELF hash、源码身份、实际 rw ext4 根设备、p1/p2 几何和实际 p1 全分区 hash，不挂载、不重启、不写介质。运行时通过标志不单独证明冷启动，需要结合本轮完整串口日志。

证据至少包括 `$log` 的预检/UUU/读回记录、`$coldlog/serial.log` 的独立 eMMC 冷启动和板端检查输出，以及最终包 SHA256SUMS。取得这些证据后才能标记 U-Boot 板级验收通过；当前状态仍为 pending，也不据 BusyBox 结果关闭 BR/systemd 验收。

## 7. 其他操作，不与 --all 混用

仅部署 U-Boot，不要求系统包：

```sh
"$u/flash.py" bootloader --firmware "$fw" --dry-run
"$u/flash.py" bootloader --firmware "$fw"
```

只写 boot0 镜像和启动设置，保护整个实际 user area 与 boot0 非镜像范围；旧分区布局不必匹配 04。但新 U-Boot 按 p1 FAT/extlinux 启动，单独部署不迁移旧 Linux 布局，可能留在控制台。写前/写后读取完整 user area，两遍比较可能耗时数分钟；保护容量超限则写前拒绝，不缩减范围。

已建立本轮布局后才做独立组件更新，每次回到 ROM USB 下载模式：

```sh
"$u/flash.py" kernel --package "$pkg" --dry-run
"$u/flash.py" kernel --package "$pkg"
"$u/flash.py" dtb --package "$pkg" --dry-run
"$u/flash.py" dtb --package "$pkg"
"$u/flash.py" rootfs --package "$pkg" --dry-run
"$u/flash.py" rootfs --package "$pkg"
```

kernel/DTB 仅替换 p1 指定文件及必要 FAT 元数据；rootfs 仅写 p2。均核验布局、实际内容和其他组件保持不变，保留 boot0、分区表和启动配置。`rtfs` 是 rootfs 别名。

## 8. 验证边界

测试命令为 `python3 -m unittest discover -s "$u/tests" -v`。测试使用主机文件和假设备，真实 UUU 只执行帮助/-dry；本轮没有真实板卡写操作。主机准备证据在 `uboot/artifacts/busybox-validation-host-audit/collection.json`。

这不是 A/B 或原子更新；断电、超时、断连可能留下半写介质，需用已知良好包恢复。Hash/快照不是签名、安全启动或对恶意同用户进程的安全边界。实际 USB 切换、Sparse 分块、eMMC 读写和冷启动均待本板验证。
