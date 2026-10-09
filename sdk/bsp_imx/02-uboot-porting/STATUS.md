# 06 · 验收状态与证据

截至 2026-10-06，当前 U-Boot 已从 eMMC 启动，并通过控制台启动现有 vendor Linux 4.9.88，进入原 rootfs 的 root shell。用户确认了 eMMC 启动；串口记录（`evidence/2026-10-06-uuu-audit/cold-boot-vendor-serial.log`）保留烧录后的上电输出、Linux 启动和登录结果。

本文件维护板级启动验收状态和证据入口。代码设计见 [01 · 移植设计](PORTING.md)，构建与系统启动见 [RAM_BOOT.md](RAM_BOOT.md)。

## 已验证的启动链路

| 项目 | 当前结果 | 证据 |
|---|---|---|
| RAM 下载与运行 | 主线 U-Boot 2026.07 运行，控制台可用 | RAM 修正版记录（`evidence/2026-10-06-mbr/collection.json`） |
| vendor Linux 交接 | 加载现有 Kernel 和 DTB，进入 Linux 4.9.88 root shell | 同上及后续启动日志 |
| eMMC 写入 | boot0 从 1024 字节处写入 351232 字节，全量逐字节比较通过 | 写入记录（`evidence/2026-10-06-emmc/collection.json`） |
| eMMC 启动 | 新 U-Boot 上电运行，再引导原 vendor 系统 | 后续串口日志（`evidence/2026-10-06-uuu-audit/cold-boot-vendor-serial.log`）与用户确认 |
| 当前 boot0 内容 | 镜像 CRC32 与主机镜像相同 | 当前串口取证（`evidence/2026-10-06-uuu-audit/collection.json`） |

当前镜像使用 UART1，控制台为 1500000 baud、8N1。eMMC 为 USDHC2 上的 MMC 设备 1，启动选择为 boot0。vendor 系统位于 user area 的 DOS 第 2 分区，Linux 控制台使用 115200 baud。

[UUU 用法与主机烧录方案](../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## 尚未验收的内容

当前配置停在控制台，没有默认 `bootcmd`，环境仅保存在 RAM。自动启动和环境持久化尚未配置。这两项不影响已经完成的手工系统启动验收。

DDR 只完成局部测试。当前结果不代表完整内存稳定性、温度范围或全部外设验收。

## 历史证据入口

首轮 RAM 记录（`evidence/2026-10-06/collection.json`）保留 DOS 分区解析遗漏的过程。修正版 RAM 记录（`evidence/2026-10-06-mbr/collection.json`）保留修复后的文件加载和 Linux 启动结果。
