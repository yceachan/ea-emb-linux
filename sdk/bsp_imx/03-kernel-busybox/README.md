# Kernel / BusyBox 板级工作区

需求与验收在 [.issues/closed/01-feat-kernel-busybox/issue.md](.issues/closed/01-feat-kernel-busybox/issue.md)，技术决策在 [adr.md](.issues/closed/01-feat-kernel-busybox/adr.md)。当前板级输入、外设覆盖和未决项见 [PORTING.md](PORTING.md)。

03 已关闭，目标镜像烧录及板上 shell 已由用户确认，交付结果见 [close.md](.issues/closed/01-feat-kernel-busybox/close.md)。

## Kernel 构建入口

以下命令只在主机生成新的源码快照和输出，不烧录板卡；SDK 构建由开发者审阅后执行。修改板级输入后应使用新的构建目录，避免旧快照混入新输入。

```sh
cd /home/pi/ea-emb-linux/sdk/bsp_imx/03-kernel-busybox
mkdir -p /home/pi/ea-emb-linux/sdk/bsp_imx/build
./kernel/build.sh configure /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-linux-7.2.9-r1
./kernel/build.sh dtb /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-linux-7.2.9-r1
./kernel/build.sh build /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-linux-7.2.9-r1
```

`configure` 固定提交并合入 DTS/注册 patch/配置片段，检查解析后的配置。`dtb` 只构建本板 DTB 并打开 W=1 告警，便于先审查。`build` 生成 zImage 和本板 DTB，不构建全部板卡或模块。

产物在构建目录 `out/arch/arm/boot/zImage` 和 `out/arch/arm/boot/dts/nxp/imx/imx6ull-100ask-pro.dtb`；源码身份、输入摘要、配置和产物校验清单在同一 `out/` 下。配置未满足片段要求时脚本失败，需要分析原因，不能直接删掉检查项。

完整日志在构建目录，交付时归档到本工作区 `artifacts/`。

## BusyBox 与 rootfs 入口

开发者构建、打包命令和文件树运行方法见 [rootfs/README.md](rootfs/README.md)。使用已烧录的 02 U-Boot 直接烧录 eMMC p2 和手工启动的方案见 [DEPLOY.md](DEPLOY.md)。
