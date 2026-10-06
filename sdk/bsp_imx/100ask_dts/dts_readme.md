| 硬件资源 / 接口 | 设备树节点 | 配置与用途 | 当前配置状态 |
|---|---|---|---|
| CPU | `cpu0` | 单核 Cortex-A7；频率表包含 198～900 MHz 档位 | 已描述，实际运行频率由系统决定 |
| DDR 内存 | `memory` | 起始地址 `0x80000000`，容量 **512 MiB** | 已配置 |
| 连续 DMA 内存池 | `linux,cma` | 从内存中划出 **320 MiB** | 已配置 |
| **HDMI 接口** | `sii902x@39`、`sii902x_reset` | SiI902x 转换芯片；I²C2 地址 `0x39`；中断 GPIO1_IO18；74HC595 控制复位；声明模式 **1280×720@60** | **已启用** |
| **M.2 4G 接口** | `reg_usb_ltemodule`、可能关联 `usbotg2` | LTE 电源 **3.8 V**，GPIO5_IO05 高电平使能，启动时供电；USB2 为 Host。是否接到 M.2 插槽需看原理图，USB 模块通常通过枚举识别 | **已配置供电和 USB Host，插槽接线尚未确认** |
| **SD 卡接口** | `usdhc1` | 4 位总线；GPIO1_IO19 低电平检测插卡；休眠保持供电、SDIO 唤醒 | **已启用** |
| eMMC / 固定存储接口 | `usdhc2` | 8 位总线、不可移除；通常接 eMMC，容量未定义 | 已启用 |
| 双以太网接口 | `fec1`、`fec2` | 两路 RMII；共享 MDIO，PHY 地址 0、1；复位 GPIO5_IO09、GPIO5_IO06 | 两路均启用 |
| CAN 接口 | `flexcan1`、`reg_can_3v3` | UART3_CTS/RTS 焊盘复用为 CAN TX/RX；收发器供电 3.3 V | CAN1 启用；CAN2 禁用 |
| 调试串口 | `uart1`、`chosen` | UART1 TX/RX；作为控制台输出 | 已启用 |
| RS-485 串口 | `uart3`、`pinctrl_485_ctl` | 声明启动时开启 RS-485；GPIO5_IO00 配为方向控制引脚，但方向控制 GPIO 属性被注释 | UART3 启用；方向控制需核对驱动 |
| 扩展串口 | `uart6` | CSI_MCLK、CSI_PIXCLK 焊盘复用为 TX/RX | 已启用 |
| USB OTG 接口 | `usbotg1`、`usbphy1` | USB1 配置为 OTG | 已启用 |
| USB Host 接口 | `usbotg2`、`usbphy2` | USB2 配置为 Host，禁用过流检测 | 已启用 |
| I²C 扩展接口 | `i2c1` | 100 kHz；UART4 TX/RX 焊盘复用为 SCL/SDA；未声明子设备 | 已启用 |
| I²C 外设总线 | `i2c2` | 连接 WM8960、SiI902x、GT9xx；频率属性写成 `clock_frequency`，需核对 | 已启用 |
| SPI 扩展接口 | `ecspi1` | 两路片选：GPIO4_IO26、GPIO4_IO24；两个 `spidev` 子节点均被注释 | 控制器启用，未声明有效子设备 |
| ICM20608 传感器 | `ecspi3` → `icm20608@0` | SPI 最高 8 MHz；片选 GPIO1_IO20；中断 GPIO1_IO01 | 已启用 |
| GPIO 扩展芯片 | `spi4` → `gpio_spi@0` | GPIO 模拟 SPI 驱动一片 **74HC595**；用于扩展控制信号，包括 HDMI 复位 | 已启用 |
| LCD 接口 | `lcdif`、`display0` | 24 位总线、24 bpp；实际时序 **1024×600**，像素时钟 50 MHz；复位 GPIO3_IO04 | 已启用；时序节点名误写为 1024×768 |
| LCD 背光 | `backlight`、`pwm1` | PWM1 输出位于 GPIO1_IO08 焊盘；9 档亮度，默认索引 8 | 已启用 |
| 图像处理 | `pxp`、`pxp_v4l2` | PXP 图像处理及 V4L2 接口 | 已启用 |
| 音频接口 | `sound`、`sai2`、`wm8960@1a`、`asrc` | SAI2 连接 WM8960；I²C2 地址 `0x1a`；耳机、扬声器、麦克风路由；ASRC 采样率转换 | 已启用 |
| Goodix 触摸屏 | `gt9xx@5d` | I²C2 地址 `0x5d`；中断 GPIO1_IO05；复位 GPIO5_IO02；800×480、最多 5 点 | 已启用 |
| 片上触摸控制器 | `tsc` | 使用 GPIO1_IO01～04 对应引脚 | 已启用；与传感器中断、ADC 引脚重叠 |
| ADC 模拟输入 | `adc1` | `num-channels = <5>`；参考电压 3.3 V；引脚组包含 GPIO1_IO03、04 | 已启用；与 TSC 引脚重叠 |
| 用户按键 | `gpio-keys` | GPIO5_IO01 → `KEY_1`；GPIO4_IO14 → `KEY_2`；低电平有效，支持唤醒 | 默认可用 |
| CPU 指示灯 | `leds` → `cpu` | GPIO5_IO03，低电平点亮；声明心跳触发 | **已禁用** |
| Wi-Fi 电源 | `reg_gpio_wifi` | 3.3 V；GPIO1_IO10 低电平使能；声明启动时供电 | 仅配置供电，未声明 Wi-Fi 通信设备 |
| 看门狗 | `wdog1`、`wdog2` | 两路片上看门狗 | WDOG1 启用；WDOG2 禁用 |
| GPIO 与引脚复用 | `gpio1`～`gpio5`、`iomuxc`、`iomuxc_snvs` | 5 组 GPIO；配置引脚功能、上下拉及电气参数；GPIO 可产生中断 | 已描述，并被各外设引用 |
| 中断与 DMA | `intc`、`gpc`、`sdma`、`dma_apbh` | GIC 中断控制、低功耗中断管理、SDMA、4 通道 APBH DMA | 基础节点默认可用 |
| 片上 SRAM | `ocrams`、`ocrams_ddr`、`ocram`、`ocram_optee` | 描述低功耗、DDR、通用及 OP-TEE 相关 SRAM 区域 | 已描述 |
| 时钟与电源管理 | `clks`、`anatop`、`reg_arm`、`reg_soc`、`reg_3p0`、`busfreq`、`src` | 24 MHz / 32.768 kHz 时钟源、CPU/SoC 电源、总线调频、复位控制 | 基础节点默认可用 |
| RTC、关机、电源键、温度 | `snvs_rtc`、`snvs_poweroff`、`snvs_pwrkey`、`tempmon` | 片上 RTC、系统关机、电源键唤醒、温度监测 | 基础节点默认可用 |
| 定时器 | `gpt1`、`gpt2`、`epit1`、`epit2` | 两路 GPT；两路 EPIT 地址及中断描述 | 已描述；EPIT 未提供 `compatible` |
| OTP、加密与随机数 | `ocotp`、`dcp`、`rngb`、`csu`、`romcp` | OTP 熔丝、加密模块、随机数及安全/系统寄存器 | CSU 禁用；其余默认可用 |
| 其他通信控制器 | UART2/4/5/7/8、I²C3/4、ECSPI2/4 | 芯片内部有这些控制器，板级文件未开启 | 已禁用 |
| 其他 PWM | `pwm2`～`pwm8` | 芯片级节点存在，板级文件未配置其输出引脚或用途 | 未显式禁用，未配置板级用途 |
| NAND、QuadSPI、外部存储总线 | `gpmi`、`qspi`、`weim`、`mmdc` | NAND/BCH、QuadSPI、WEIM 外部总线、DDR 控制器 | NAND、QuadSPI 禁用；WEIM 未挂子设备；MMDC 已描述 |
| 其他显示、音频及输入资源 | `csi`、`epdc`、`sai1/3`、`spdif`、`esai`、`mqs`、`kpp`、`pmu` | 摄像头、电子纸、其他音频接口、矩阵键盘、CPU 性能监测 | 已禁用 |
| 状态含义与来源 | [板级 DTS](/home/pi/ea-emb-linux/sdk/bsp_imx/100ask_dts/100ask_imx6ull-14x14.dts)、[芯片级 DTSI](/home/pi/ea-emb-linux/sdk/bsp_imx/100ask_dts/imx6ull.dtsi) | “已启用”表示合并后的节点配置允许驱动使用；“默认可用”表示未设置 `disabled` | 不代表已经验证实际接线、内核驱动或硬件运行 |