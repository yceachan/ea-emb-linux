# Linux 7.2.9 板级移植输入

当前输入是可审查的移植候选，覆盖已经确认的启动资源及可用主线绑定。用户已确认 HDMI 启用、AP3216C 和无线功能留后续；供电差异与驱动/固件缺口明确保留在清单中。本轮内核与本板 DTB 已由开发者构建并复核；DT schema 验证及目标内核实板验收尚未执行。

## 输入组织

`kernel/base-revision` 固定本地源码身份。`kernel/overlay/arch/arm/boot/dts/nxp/imx/imx6ull-100ask-pro.dts` 是唯一板级入口，直接包含目标源码的 `imx6ull.dtsi`，不复制 vendor SoC DTSI。`kernel/register-board.patch` 注册 DTB 和本板 compatible；`kernel/board.config` 合入 `imx_v6_v7_defconfig`。构建脚本检查最终配置是否保留了片段要求。

板级接线由下表维护；默认启动与部署决策由 issue 的 ADR 维护。实板来源见 `artifacts/2026-10-07-154632-vendor-survey/collection.json`，图纸来源见 `artifacts/2026-10-07-pin-audit/sources.json`。

## 板级资源映射

“候选已描述”表示 DTS 使用目标绑定表达该连接；不等于已经 probe 或功能通过。图纸标为 STD V1.1，使用它核对 PRO 板时保留版本差异边界。

| 资源 | 本板连接与目标表达 | 当前处置 |
|---|---|---|
| DDR | `memory@80000000`，512 MiB；承接 DCD/U-Boot 初始化 | 候选已描述；Linux 内存与稳定性待验收 |
| UART1 | UART1 TX/RX pad，`serial0:1500000n8`，`ttymxc0` | 候选已描述；速率待目标内核实测 |
| eMMC | USDHC2、NAND DATA00～07、8 位、不可移除；继承 `mmc1` alias | 候选已描述；不新增高速状态，保留既有 U-Boot 的禁止 1.8 V 切换策略 |
| SD | USDHC1、4 位，GPIO1_IO19 插卡检测 | 候选已描述；不占用 GT911 的 IO05 作为 VSELECT |
| 双网口 | 两路 RMII；FEC2 MDIO 地址 0/1；GPIO5_IO09/06 复位 | 分开 pinctrl；复位迁到 PHY 节点，26 ms assert；功能待验收 |
| CAN1 | UART3 CTS/RTS pad 复用为 CAN TX/RX，3.3 V 收发器电源 | 候选已描述；SoC 节点标签为 `can1`，CAN2 保持禁用 |
| UART3/RS-485 | UART3 TX/RX；GPIO5_IO00 控制 SP3485 共接的 DE 与低有效 RE | 使用 `rts-gpios`；发送高、接收低；去掉无法同时接收的 `rs485-rx-during-tx`；沿用 100/100 ms 延时，实际时序待测试 |
| UART6 | CSI MCLK/PIXCLK pad 复用为 TX/RX | 候选已描述；camera 的这些 pad 不可同时使用 |
| I²C1 | UART4 TX/RX pad，100 kHz | 总线已描述；AP3216C 子设备见未决项 |
| I²C2 | UART5 TX/RX pad，100 kHz | 修正 `clock_frequency` 为 `clock-frequency` |
| ECSPI1 扩展 | CSI DATA04/06/07；GPIO4_IO26/24 两路片选 | 控制器已描述；不创建没有实物依据的 spidev 设备 |
| ICM20608 | ECSPI3、8 MHz；GPIO1_IO20 CS，GPIO1_IO01 rising IRQ | 候选已描述；增加主线 `INV_MPU6050_SPI` 内建配置 |
| 74HC595 | GPIO5_IO11 SCLK、IO10 SER、IO07 RCLK/锁存、IO08 低有效 OE | 主线 `spi-gpio` 与 `74x164`，`lines-initial-states=<0x57>`；片选使用低有效锁存语义，OE 在写初值后启用 |
| LCD | LCDIF 24 根 RGB 数据线；GPIO3_IO04 低有效 reset；GPIO1_IO09 DISP；1024×600，50 MHz，porch 160/140/20、12/20/3 | 默认唯一 DRM sink；RGB graph + panel-dpi；DISP 为 enable；reset 由 GPIO hog 保持解除，不声称提供 reset 脉冲序列 |
| LCD 背光 | GPIO1_IO08 PWM1，1 µs 周期；原 9 档亮度表 | 候选已描述；背光挂在 panel 上 |
| GT911 | I²C2 0x5d；GPIO1_IO05 IRQ、GPIO5_IO02 reset；1024×600 | 主线 Goodix；IRQ/reset GPIO flags 使用高有效的驱动逻辑约定，保持复位低→高与 0x5d 地址选择；不复制 vendor 配置字节与私有属性 |
| 片内 TSC | IO01～04 与 IMU IRQ/ADC 重叠，实板 vendor probe 失败 | 明确禁用；本板触摸使用 GT911 |
| ADC1 | GPIO1_IO03/04 对应外部通道；3.3 V vref | 删除目标绑定不支持的 `num-channels`；主线驱动自行提供通道，未声明所有通道都有外部接线 |
| WM8960 | I²C2 0x1a；JTAG pad 复用 SAI2；MCLK 12.288 MHz | 主线 `fsl,imx-audio-wm8960`，`audio-cpu`/`audio-codec`/`audio-asrc`；codec-master 由该驱动匹配项建立；不继承无效 `gpr`/`hp-det` |
| ASRC/PXP | 目标 SoC 节点与驱动 | 启用既有节点；不复制 vendor 独立 PXP V4L2 软件节点 |
| USB1 | OTG，GPIO1_IO00 ID | 候选已描述；不继承无依据的 PHY 私有校准值 |
| USB2/USB Hub | Host，实板枚举 SMSC 0424:2514；Hub reset 接 74HC595 QC/line2 | Host 已描述；初始 0x57 使 line2 为高，保留既有 reset 解除状态；Hub 按 USB 枚举发现 |
| 按键 | GPIO5_IO01 KEY_1、GPIO4_IO14 KEY_2，低有效 | 补足两组 pinctrl，使用 `wakeup-source` |
| CPU LED | GPIO5_IO03，低有效 | 保留 vendor 的禁用策略，节点与接线仍在 |
| 看门狗/RTC/温度/OTP/时钟/中断/DMA | 目标 `imx6ull.dtsi` 及其依赖 | 沿用主线 SoC 描述，开启 WDOG1/SNVS poweroff/pwrkey；不迁入 vendor busfreq、OP-TEE SRAM 等软件布局 |
| HDMI | 图纸 U12 SIL9022A；I²C2 0x39、GPIO1_IO18 IRQ；74HC595 QB/line1 reset | 已确认默认禁用；保留标准 compatible/地址/复位/IRQ，graph 和启用留后续对齐 |

## 延后外设与资料缺口

| 项目 | 冲突或缺口 | 本轮输入边界 |
|---|---|---|
| Wi-Fi 电源 | vendor 使用 GPIO1_IO10；图纸由 74HC595 QD/line3 控制 PMOS，低电平供电。实板 USB 已枚举 0bda:b720，但没有证明 GPIO1_IO10 的接线 | 不把 vendor GPIO 原样写入候选；保留 0x57 的 QD 低状态。是否正式描述 line3 固定电源及 USB 子设备，先确认图纸适用于实板 |
| Wi-Fi 驱动/固件 | 目标 `rtl8xxxu` 支持 RTL8723BU，但需要固件；USB 枚举不等于无线网络可用 | 当前不宣称完成 Wi-Fi 驱动/固件交付；待确定该项仅描述还是包含可运行支持 |
| 4G 供电 | GPIO5_IO05 使能已见图纸；图纸标称 VDD_4G_3.4V，vendor 写 3.8 V；实板没有枚举 4G 模块 | 暂不硬写固定电压或启动供电策略，需板卡版本/实物电源确认；USB 连接在图纸中为 Hub port2 |
| AP3216C | 图纸 U9 接 I²C1，旧 DTS 未声明；目标源码未发现对应驱动/绑定 | 已确认留后续补驱动/绑定；当前保留资源记录，不添加没有驱动支持的兼容字符串 |
| LCD 面板完整身份 | 已知尺寸与运行时序，面板型号、物理尺寸、reset 时序尚未确认 | compatible 前缀表示本板 LCD 组合，不假称已识别厂家型号；不填物理尺寸。panel-dpi 无 bpc/bus-format，mxsfb 会使用 RGB888 默认值，驱动可能打印缺失参数告警；显示功能验收前应完善具体 panel 描述 |

## 内核配置与检查边界

最小启动链要求 UART、MMC block、i.MX USDHC、DOS 分区解析、ext4、devtmpfs 内建。本阶段支持的板级传感器和音频驱动也改为内建，避免只生成 DT 节点却忘记交付其模块。广泛的 i.MX 基础 defconfig 尚未裁剪；其余模块不在当前产物交付范围内。

不复制 vendor 的 320 MiB CMA 节点。配置暂沿用基础 defconfig 的 64 MiB 默认 CMA，这个值是首轮构建基线，未声称根据完整显示/PXP 负载测定。DDR 验收应记录真实内存布局。

本轮仅完成 cpp + 既有 host dtc 对目标源码 DTSI 的语法、引用检查，DTB 无 dtc 告警；该记录本身不代表绑定 schema 通过；后续开发者 make 构建已完成，复核索引见 `artifacts/2026-10-07-kernel-build-review/collection.json`。主机目前缺少 dtschema。检查记录见 `artifacts/2026-10-07-kernel-input-audit/collection.json`。
