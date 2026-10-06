# 02 · 主机统一脚本

`uboot.py` 统一 RAM 下载、eMMC 烧录和串口控制台。脚本复用产物中的 `ram-boot.uuu` 和 `emmc-flash.uuu`，不改变 U-Boot 的启动行为。RAM 下载后默认进入控制台，只有 `emmc` 模式自动发送 `fastboot usb 0`。

## 运行条件

主机需要 Python 3、pyserial、UUU 和 `sha256sum`。当前主机已安装这些依赖，并具备串口和 USB 访问权限。脚本不自动提权。关闭 minicom 等其他串口程序，避免同时读写同一个设备。

`ram` 和 `emmc` 模式要求板卡已进入 ROM USB 下载模式，OTG1 和串口都已连接。先断电，记录原 eMMC 启动拨码，再按板卡说明切换下载模式并上电。脚本要求主机恰好识别一个 `15a2:0080` 下载设备，并用 UUU 的 `-m` 参数固定该设备的 USB 路径。

默认串口为 `/dev/ttyACM0`，使用 1500000 baud、8N1，无硬件或软件流控。默认产物目录为脚本旁的 `artifacts/`。构建步骤见 [RAM_BOOT.md](RAM_BOOT.md#构建)。

## RAM 调试

在仓库根目录执行以下命令。脚本核对产物校验清单，执行 UUU 预检，再下载镜像。收到本轮 U-Boot 板名和提示符后，脚本进入交互控制台，不发送 fastboot 命令：

```sh
cd /home/pi/ea-emb-linux
sdk/bsp_imx/02-uboot-porting/uboot.py ram
```

控制台中，`Ctrl-C` 发送给板卡。`Ctrl-]` 退出主机脚本并释放串口，不重启板卡。重新连接当前控制台时使用 `console` 模式：

```sh
sdk/bsp_imx/02-uboot-porting/uboot.py console
```

## eMMC 烧录

`emmc` 模式会写入 eMMC。它沿用[现有烧录脚本](emmc-flash.uuu)的区域选择与全量读回比较，不备份镜像，不修改启动选择。操作范围见 [EMMC_FLASH.md](EMMC_FLASH.md)。

板卡处于 ROM USB 下载模式时，在主机执行以下命令。脚本下载 U-Boot，等待本轮启动提示符，再自动发送 fastboot 命令。UUU 随后完成写入和读回比较：

```sh
sdk/bsp_imx/02-uboot-porting/uboot.py emmc
```

脚本检查 UUU 全部命令的成功记录，以及与镜像长度一致的串口比较结果。成功后，脚本发送 `Ctrl-C` 退出 fastboot，确认控制台提示符，再进入交互控制台。它不会自动重启或启动 Linux。

完成后退出脚本，将板卡断电，恢复 eMMC 启动拨码，再上电。按 [vendor Linux 启动步骤](RAM_BOOT.md#手工启动-vendor-linux)验收持久启动。写入期间若中断，先检查日志与 eMMC 内容，再决定后续操作。

## 预检、参数与日志

只核对文件和 UUU 脚本时，使用 `--dry-run`。此模式不连接串口，不下载或写入板卡。RAM 和 eMMC 两种预检命令如下：

```sh
sdk/bsp_imx/02-uboot-porting/uboot.py ram --dry-run
sdk/bsp_imx/02-uboot-porting/uboot.py emmc --dry-run
```

默认情况下，下载或烧录的总时限为 60 秒。使用 `--timeout` 调整时限。自动运行时使用 `--no-console`，完成后退出脚本。它仍采集串口，并在烧录成功后确认退出 fastboot：

```sh
sdk/bsp_imx/02-uboot-porting/uboot.py ram --no-console --timeout 120
```

`--artifacts` 指定另一份完整产物目录，`--serial` 指定串口，`--baudrate` 指定速率。向当前 vendor Linux 交接时，先在 U-Boot 执行 `setenv baudrate 115200`，然后用 `Ctrl-]` 退出脚本，再以新速率连接：

```sh
sdk/bsp_imx/02-uboot-porting/uboot.py console --baudrate 115200
```

每次运行都打印日志目录，默认位于 `logs/` 的独立子目录。`serial.log` 保存原始串口输出，`uuu.log` 保存实际下载或烧录输出，其他日志保存文件校验、预检和 USB 设备列表。`--log-dir` 指定自选目录，该目录必须尚不存在。

脚本同时检查进程退出码与 UUU 的 Error、Fail 记录。当前 Snap 启动器返回零退出码时，也不能掩盖 UUU 失败。成功条件还包括完整的命令执行记录，不能用缺失日志判定成功。
