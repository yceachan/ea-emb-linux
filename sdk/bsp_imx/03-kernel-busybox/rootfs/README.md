# BusyBox rootfs 构建与运行

本目录统一维护 BusyBox 构建和目标 rootfs：`build.sh`、`board.config`、`base-revision`、`package.py` 与 `overlay/`。BusyBox 固定为 1.36.1，采用 ARM Cortex-A7 hard-float 静态链接。正常系统以 BusyBox init 为 PID 1，直接进入串口 root ash shell。

## 已有产物

当前 `artifacts/2026-10-07-busybox-r2/rootfs.tar.gz` 已包含 `/boot/zImage`、本板 DTB、extlinux 配置与 BusyBox 文件树。rescue 路线已取消，相关源码和包体已删除。现有归档仍可用于制作 ext4 镜像，无需重新编译。分区镜像制作和启动验收见 [DEPLOY.md](../DEPLOY.md)。

## 新构建与打包

SDK 完整构建由开发者审阅后执行。修改 BusyBox 编译输入后使用新构建目录；仅改变 rootfs 文件树时，可复用已校验的 BusyBox 安装树重新打包。

```sh
cd /home/pi/ea-emb-linux/sdk/bsp_imx/03-kernel-busybox
./rootfs/build.sh configure /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-busybox-1.36.1-r3
./rootfs/build.sh build /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-busybox-1.36.1-r3
python3 rootfs/package.py     /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-busybox-1.36.1-r3     /home/pi/ea-emb-linux/sdk/bsp_imx/build/100ask-linux-7.2.9-r1/out     /home/pi/ea-emb-linux/sdk/bsp_imx/03-kernel-busybox/artifacts/2026-10-07-rootfs-r3
```

配置由 allnoconfig 与显式 applet 选择生成，并检查解析后的结果。构建使用 `-j12`，核对 ELF 的 ARM hard-float ABI 及无动态加载器/共享库依赖。打包核验二进制、编译配置输入与源码版本、kernel/DTB 的校验清单及安装树 applet 链接。

打包的最后一个参数必须是新目录，输出 `rootfs/`、`rootfs.tar.gz`、独立 `zImage` 与 DTB，以及校验清单和来源信息。tar 固定 UID/GID 为 0，保留权限和符号链接，不在主机创建设备节点。

## 初始化与串口

inittab 先执行 rcS，再在 `ttymxc0` 上启动读取 `/etc/profile` 的 root ash shell，无登录验证。console-shell 设置 1500000 baud、8N1，关闭硬件与软件流控，然后 exec ash。shell 有控制终端，支持 Ctrl-C、作业控制及退出后重新进入。

内核挂载 devtmpfs；rcS 初始化 proc、sysfs、tmpfs `/run`/`/tmp` 与 hostname。必要步骤失败时停在维护路径，保持 PID 1 存活，不打印正常启动完成提示。`/run`、`/tmp` 为易失数据，其余目标文件位于 rw ext4。本阶段不配置网络或启动网络服务。关机路径同步后卸载或转为只读。

## 主机检查

```sh
python3 -m unittest discover -s tests -v
```

测试检查目标文件树组装、tar 元数据和部署控制行为，不访问板卡。

[UUU 用法与主机烧录方案](../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)
