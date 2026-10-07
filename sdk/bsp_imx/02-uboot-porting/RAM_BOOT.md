# 03 · 构建、ROM 下载与系统启动

本文件维护本板构建、RAM 下载和手工启动 vendor Linux 的命令。当前验收状态见 [06 · 验收状态](STATUS.md)。只写 eMMC U-Boot 时，使用 [EMMC_FLASH.md](EMMC_FLASH.md)的流程。

## 构建

在主机仓库根目录执行以下命令。`configure` 生成源码快照和配置，构建目录必须尚不存在。示例使用 `100ask-imx6ull-next`，若目录已存在，为新一轮选择新的目录名。

```sh
cd /home/pi/ea-emb-linux
sdk/bsp_imx/02-uboot-porting/build.sh configure "$PWD/sdk/bsp_imx/build/100ask-imx6ull-next"
sdk/bsp_imx/02-uboot-porting/build.sh build "$PWD/sdk/bsp_imx/build/100ask-imx6ull-next"
```

完整构建由开发者执行。修改 `overlay/`、注册补丁或脚本后，重新生成源码快照。对旧目录执行 `build` 不会自动同步 BSP 修改。构建失败时，读该目录的 `build.log`，不要用旧产物代替本轮结果。

构建成功后，`artifacts/` 保存镜像、配置、源码记录、UUU 脚本和校验清单。下载镜像为带 i.MX ROM 头的 `u-boot-dtb.imx`。在主机查看镜像信息：

```sh
cd /home/pi/ea-emb-linux/sdk/bsp_imx/02-uboot-porting/artifacts
cat image-info.txt
```

`ram-boot.uuu` 只执行 DCD、RAM 写入、跳转和完成操作，不写 eMMC。DCD 是 ROM 初始化 DDR 的配置。下载前先按 [HOST_TOOL.md 的正式运行前预检](HOST_TOOL.md#正式运行前的预检)校验产物和 UUU 脚本，检查通过后再操作板卡。

## 串口与 ROM 下载

RAM 下载和控制台统一由 [uboot.py](uboot.py)管理。板卡准备、命令和控制台退出方法见 [HOST_TOOL.md](HOST_TOOL.md#ram-调试)。脚本在 RAM 模式中不进入 fastboot，不写 eMMC。

新 U-Boot 使用 1500000 baud、8N1。串口必须出现本轮版本、`Board: 100ask i.MX6ULL Pro (UART1 / eMMC)` 和 `=>`。当前 `bootdelay=-1` 保留调试控制台。

## 手工启动 vendor Linux

以下命令用于当前 eMMC 的现有 vendor 系统。MMC 设备 1 的 user area 第 2 分区保存 Kernel、DTB 和 rootfs。在 U-Boot 控制台逐条执行：

```text
version
mmc dev 1 0
mmc part
ext4load mmc 1:2 0x82000000 /boot/zImage
ext4load mmc 1:2 0x83000000 /boot/100ask_imx6ull-14x14.dtb
```

当前 zImage 长度为 8846320 字节，DTB 长度为 38370 字节。若加载失败，保留输出并停止启动。若成功，设置当前系统的串口和根盘参数：

```text
setenv bootargs console=ttymxc0,115200 root=/dev/mmcblk1p2 rootwait rw
setenv baudrate 115200
```

U-Boot 切换速率后，按 [HOST_TOOL.md](HOST_TOOL.md#参数与日志)重新连接 115200 baud 控制台。保持 8N1 和无流控。按 Enter 恢复 `=>`，再执行：

```text
bootz 0x82000000 - 0x83000000
```

进入 root shell 后采集以下输出。保存从 U-Boot 到 shell 的完整串口日志。当前流程以 Linux 4.9.88、原 rootfs 和可用 root shell 为验收条件：

```sh
uname -a
cat /proc/cmdline
mount
```

## 板级诊断命令

需要调查控制台、DDR 或 eMMC 时，在 U-Boot 控制台运行下列只读诊断。`mmc dev 1 0` 选择 user area，不更改持久启动选择。输出必须与本板设备树和 DDR 配置一致：

```text
bdinfo
clocks
printenv baudrate
md.l 0x020200a4 2
mmc list
mmc dev 1 0
mmc info
mmc partconf 1
mmc part
ext4ls mmc 1:2 /boot
```

当前 DDR 起点为 `0x80000000`，容量为 512 MiB。UART 输入时钟为 80 MHz，UBIR=2、UBMR=4。eMMC 为 S40004，容量约 3.6 GiB，使用 8 位总线。

需要比较重复加载结果时，每次加载 zImage 后执行 `crc32 0x82000000 ${filesize}`。已有读取结果为 `52f62257`。CRC32 只用于内容比较，不能证明 Kernel 与硬件兼容。测试记录随本轮镜像和日志归档，不替代系统启动验收。
