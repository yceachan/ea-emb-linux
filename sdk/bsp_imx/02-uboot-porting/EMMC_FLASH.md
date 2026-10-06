# 04 · eMMC U-Boot 烧录

当前 `emmc-flash.uuu` 使用官方 UUU 下载 U-Boot 到 RAM，再通过 fastboot 写入 eMMC。脚本读取当前启动选择，写入对应区域，并逐字节比较读回内容。当前验收状态由 [06 · 验收状态](STATUS.md)维护，官方内置命令适配由 [UUU_COMPAT.md](UUU_COMPAT.md)维护。

## 下载与写入

构建步骤见 [RAM_BOOT.md](RAM_BOOT.md#构建)。修改 BSP 后，必须使用新构建目录重新生成源码快照。最近一次产物在 `artifacts/`，烧录脚本与镜像必须来自同一次交付。

使用 [HOST_TOOL.md 的 eMMC 模式](HOST_TOOL.md#emmc-烧录)准备板卡和启动统一脚本。主机自动完成 ROM 下载、等待新 U-Boot 提示符、进入 fastboot 和烧录，不需要另一终端手工发送命令。当前验收状态由 STATUS.md 维护。

USB fastboot 接口使用 `0525:a4a5`。烧录脚本指定 MMC 设备 1。BOOT_PARTITION_ENABLE 为 1 时写 boot0，为 2 时写 boot1，为 0 或 7 时写 user area。硬件分区编号与 DOS 分区编号不同。

脚本从第 2 扇区开始写入，即 1024 字节偏移，保留范围到 1 MiB 边界。写入后，脚本读回全部镜像并执行 `cmp.b`，最后选择 user area。脚本不改变原启动选择，不写分区表，不保存环境。

统一脚本检查每一步结果、`FB: Done` 和完整镜像比较记录。若操作失败，查看它打印的日志目录，先定位失败命令，不直接将结果标为成功。当前主机脚本的验证范围见 [06 · 验收状态](STATUS.md)。

## 写后启动验收

烧录成功后，将开发板断电，恢复 eMMC 启动拨码，再上电。此时不运行 UUU。串口保持 1500000 baud，确认新 U-Boot 版本与板名。

按 [RAM_BOOT.md 的 vendor Linux 启动步骤](RAM_BOOT.md#手工启动-vendor-linux)加载当前系统，交接时切到 115200 baud。确认 Linux 挂载原 rootfs 并进入 root shell。保存从上电到 shell 的完整串口日志，与本次镜像校验清单一同归档。
