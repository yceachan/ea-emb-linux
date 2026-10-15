---
title: uuf · GUI 使用与构建
tags: [uuf, Tauri, React]
note_types: document
created: 2026-10-15
updated: 2026-10-15
template: doc
lang: zh

---

# uuf · GUI 使用与构建

GUI 在 Linux 主机上准备归档、检查计划并操作当前 i.MX6ULL 板卡。三个页面共用 [CLI 后端](../README.md) 的参数验证、MBR／Sparse 检查与执行流程；GUI 只负责输入、计划展示和交互确认。实板写入与冷启动由开发者验收。

## 1 · 启动与构建

主机需要 Python 3.12+、UUU、e2fsprogs、fakeroot、dtc／fdtget，以及 GTK3 和 WebKitGTK 4.1。开发构建还需要 Node.js 20.19+ 或 22.12+、npm 和 Rust。系统开发依赖按 [Tauri Linux 前置要求](https://v2.tauri.app/start/prerequisites/) 准备。

从本目录执行：

```sh
npm ci
npm run tauri dev -- -- --jobs 12
```

首次窗口采用当前显示器宽高的一半，居中显示，可调整大小。小屏幕使用页面滚动和表格横向滚动。

```sh
# 编译包含前端的本地程序，不制作安装包
npm run tauri build -- --no-bundle -- --jobs 12
# Fedora 安装包
npm run tauri build -- --bundles rpm -- --jobs 12
# Debian 安装包
npm run tauri build -- --bundles deb -- --jobs 12
```

产物位于 `src-tauri/target/release/`。安装包随附 Python 后端和固定固件源码输入；固件发布目录使用 M1 构建出的 `release/`，完整归档部署则直接使用归档内固件。Python、主机工具和系统库由主机供应，UUU 可在界面指定或通过 `UUF_UUU` 设置。

开发时从源码树定位后端；打包程序通过 Tauri 的资源目录定位后端，运行不依赖源码树或 CWD。资源布局遵循 [Tauri resources](https://v2.tauri.app/develop/resources/) 的路径映射规则。

## 2 · 三个页面

| 页面 | 输入与行为 |
|---|---|
| 烧录 | 完整归档部署；勾选 U-Boot、kernel、DTB、rtfs 的独立或组合更新；明确 boot0 范围或完整分区擦除 |
| 镜像准备 | 载荷与预留量生成默认布局；读取并编辑 MBR；重建两张 ext4、编码 Sparse、打包和解包 |
| 设备信息 | RAM loader 探测 CID、容量与原始分区状态；校验归档并比较目标分区、镜像和组件映射 |

“工具与连接设置”提供固件发布目录、固件部署描述、UUU、USB 路径、任务时限和日志输出目录。多设备时明确填写 ROM USB 路径；启动项存在多个候选时明确填写实际 kernel 分区号或 LABEL。错误会停止当前任务，界面不猜测目标。

路径框支持直接输入和原生选择。“新目录”与“另存路径”使用保存对话框输入新名称，输出必须尚不存在。rootfs 可选 tar 文件或目录。选择器取消时保留原值。

## 3 · 准备归档

1. 选择 kernel、DTB、rootfs，填写分区内目标路径与预留量。
2. 指定布局新目录，点击“按载荷生成布局”。后端生成 MBR、组件目标描述和启动描述，界面自动接入这些输出。
3. 点击“读取分区表”。编辑 signature、分区起点和长度，单位为 512 字节扇区；起点和长度须按 8 扇区对齐。
4. 指定新文件，点击“检查并另存 MBR”。后端检查几何与角色，保留原输入；成功后使用新 MBR 制像。
5. 指定固件发布目录、制像新目录和归档输出，点击“重建两个 ext4 并打包”。仅在实际测定 Linux 设备号后填写 `/boot` 设备。

MBR 表项编号、Linux 类型和活动标志由现有组件映射约束。调整角色或板内文件路径时，选择对应的组件目标描述和启动描述。未保存的分区编辑会阻止打包；制像时再次核对容量、启动引用和预留量。布局更新通过完整归档部署，始终包含两张新 ext4。

“设备信息”中的归档几何取自所选归档内 MBR；编辑器显示的是准备中的布局。两者各自显示来源，部署使用烧录页实际选择的归档。

## 4 · 执行与取消

“仅主机预检”只检查输入、计划和 UUU 离线脚本，不访问板卡。计划直接显示后端给出的区域、分区、LBA／文件路径、源文件大小、分区容量和有效写入量；尚未探测的几何会明确提示待复核。

正式操作先完成相同预检，再确认主机计划。确认后才连接 ROM、下载 RAM loader 和探测实际目标。持久写入前再次展示真实 CID 和范围，输入 CID 后 8 位才能确认。后端随后复核目标和暂存输入，并执行写入与读回核验。

进度条表示任务仍在运行，不估算百分比。执行区展示实际阶段、结果与错误；界面日志保留最近 200,000 字符，设备操作的完整日志和计划写入任务目录。默认位置为 `~/uuf-logs/`，可用 `UUF_LOG_ROOT` 或界面新目录覆盖。

任务期间锁定输入。“取消任务”发送一次中断，界面持续等待后端清理；只有进程退出和管道关闭后才解除锁定。重复取消不会提前报告停止。运行时关闭窗口会要求先取消任务。已经发生的持久写入不会自动回滚，应根据任务日志检查设备状态。

## 5 · 验证

```sh
npm test
npm run build
cargo test --manifest-path src-tauri/Cargo.toml -j12
cargo clippy --manifest-path src-tauri/Cargo.toml -j12 -- -D warnings
```

真实归档的 Rust RPC／CLI 计划一致性检查：

```sh
env UUF_TEST_ARCHIVE=/absolute/path/to/system.tar.gz \
  UUF_TEST_UUU=/absolute/path/to/uuu \
  cargo test --manifest-path src-tauri/Cargo.toml -j12 -- --ignored
```

原生交互测试使用 `tauri-driver`、WebKitWebDriver、Xvfb、D-Bus、Python GI／AT-SPI 和 XTest。仅在独立会话中运行；脚本预检辅助功能服务，使用隔离的配置与数据目录。真实 UUU 只用于 `-dry`，正式执行使用本地协议模拟器，不访问 USB。

```sh
npm run tauri build -- --debug --no-bundle -- --jobs 12
env UUF_TEST_ISOLATED=1 dbus-run-session -- \
  xvfb-run -a -s '-screen 0 1920x1080x24' \
  python3 tests/native_gui.py \
    --binary "$PWD/src-tauri/target/debug/uuf-gui" \
    --native-driver /absolute/path/to/WebKitWebDriver \
    --archive /absolute/path/to/system.tar.gz \
    --bundle /absolute/path/to/unpacked-bundle \
    --firmware /absolute/path/to/firmware-release \
    --rootfs /absolute/path/to/rootfs.tar.gz \
    --uuu /absolute/path/to/uuu \
    --output /absolute/path/to/new-test-output
```

原生测试采用固定 1920×1080 显示，检查 960×540 初始窗口、实际文件选择、两次确认、故障停止、取消清理和布局编辑。协议模拟证据不替代实板验收。阶段证据统一见 `../.issues/open/02-feat-uboot-foundation/artifacts/2026-10-15-uuf-m3/collection.json`。
