# 06 · 验收状态与证据

截至 2026-10-06，当前 U-Boot 已从 eMMC 启动，并通过控制台启动现有 vendor Linux 4.9.88，进入原 rootfs 的 root shell。用户确认了 eMMC 启动；[串口记录](evidence/2026-10-06-uuu-audit/cold-boot-vendor-serial.log)保留烧录后的上电输出、Linux 启动和登录结果。

本文件维护验收状态和证据入口。代码设计见 [01 · 移植设计](PORTING.md)，操作步骤见 [02 · 主机脚本](HOST_TOOL.md)、[03 · 构建与系统启动](RAM_BOOT.md)和 [04 · eMMC 烧录](EMMC_FLASH.md)。

## 已验证的启动链路

| 项目 | 当前结果 | 证据 |
|---|---|---|
| RAM 下载与运行 | 主线 U-Boot 2026.07 运行，控制台可用 | [RAM 修正版记录](evidence/2026-10-06-mbr/collection.json) |
| vendor Linux 交接 | 加载现有 Kernel 和 DTB，进入 Linux 4.9.88 root shell | 同上及后续启动日志 |
| eMMC 写入 | boot0 从 1024 字节处写入 351232 字节，全量逐字节比较通过 | [写入记录](evidence/2026-10-06-emmc/collection.json) |
| eMMC 启动 | 新 U-Boot 上电运行，再引导原 vendor 系统 | [后续串口日志](evidence/2026-10-06-uuu-audit/cold-boot-vendor-serial.log)与用户确认 |
| 当前 boot0 内容 | 镜像 CRC32 与主机镜像相同 | [当前串口取证](evidence/2026-10-06-uuu-audit/collection.json) |
| UUU 目标映射 | 临时补入 raw partition 描述后，官方 UUU 识别 `bootloader` | 同上，协议说明见 05 号文档 |

当前镜像使用 UART1，控制台为 1500000 baud、8N1。eMMC 为 USDHC2 上的 MMC 设备 1，启动选择为 boot0。vendor 系统位于 user area 的 DOS 第 2 分区，Linux 控制台使用 115200 baud。

镜像身份和构建记录由 [USB fastboot 镜像归档](evidence/2026-10-06-uuu/collection.json)维护。后续实验引用同一镜像时，通过归档路径和校验值关联，不以 `artifacts/` 中的可覆盖文件作为历史来源。

## 主机脚本的验证范围

统一脚本的 `ram` 和 `emmc` 预检通过。8 项自动测试通过，覆盖模式选择、完整比较、失败识别、超时和返回控制台等行为。测试通过模拟串口和历史 UUU 输出执行，源码见 [tests/test_host_workflow.py](tests/test_host_workflow.py)。

实板验证了 `console` 模式的命令读写、进入 fastboot、转发 `Ctrl-C` 回到控制台，以及退出主机脚本。统一脚本的完整 ROM 下载与 eMMC 写入尚未在实板重跑。此前 eMMC 写入的验收属于直接运行 UUU 的流程，不能代替主机脚本的完整实板验收。

## 尚未验收的内容

当前配置停在控制台，没有默认 `bootcmd`，环境仅保存在 RAM。自动启动和环境持久化尚未配置。这两项不影响已经完成的手工系统启动验收。

DDR 只完成局部测试。当前结果不代表完整内存稳定性、温度范围或全部外设验收。原样 `uuu -b emmc` 只完成目标查询与主机预检，其完整烧录仍待单独验收。

## 历史证据入口

[首轮 RAM 记录](evidence/2026-10-06/collection.json)保留 DOS 分区解析遗漏的过程。[修正版 RAM 记录](evidence/2026-10-06-mbr/collection.json)保留修复后的文件加载和 Linux 启动结果。这两轮镜像不代表当前 USB fastboot 交付镜像。

[USB fastboot 首轮记录](evidence/2026-10-06-uuu/collection.json)保留镜像、构建来源和写入前的脚本失败。[eMMC 成功记录](evidence/2026-10-06-emmc/collection.json)保留修正后的写入与比较。[UUU 调查记录](evidence/2026-10-06-uuu-audit/collection.json)补充后续启动日志和当前板卡取证。
