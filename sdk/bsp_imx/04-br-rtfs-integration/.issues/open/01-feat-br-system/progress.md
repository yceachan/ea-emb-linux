# 进度

## 2026-10-10 · U-Boot 独立专章与需求更新

用户确认通用基础层需求前七条，并指定：仅当前 i.MX6ULL 板卡；MBR＋ext4；单份 Sparse＋外部描述；整盘部署更新产品 U-Boot，但先验算本轮 target hash，一致时跳过产品镜像擦写。已开 [02-feat-uboot-foundation](../02-feat-uboot-foundation/issue.md)，由其维护基础层需求／验收与待讨论问题，本父级维护 BR 系统消费目标。

最新确认取代旧 FAT32、固定几何／路径和 BusyBox 专用基础入口的实施假设；下面既往记录仍作为当时事实保留，不表示新 MBR/ext4 能力通过。仅更新文档与导航，没有新实现、构建、UUU 或板卡操作。下一项讨论为 ext4 启动区域与 rtfs 是否分离，以及怎样保证独立 rtfs Sparse 更新不覆盖 kernel/DTB。


## 2026-10-10 · 03 BusyBox 验收镜像与单份 --all 流程

按用户要求，以关闭的 03 BusyBox r2 归档及其固定 kernel/DTB 为 U-Boot 板级验收载荷，不替代后续 BR/systemd 系统。实际归档三项 SHA-256 通过，原始文件不修改；在 `build/uboot/busybox-validation/payload/` 重建 p1 FAT32＋2 GiB p2 ext4，生成真实 raw/Sparse 镜像。启动文件从旧 p2 /boot 转入 p1，BusyBox/init 与 kernel/DTB 保持基线；加入只读运行时验收脚本，直接读 p1 块设备，不依赖 Linux VFAT 或旧 /boot 副本。

已完成实际主机制像、文件系统与 root UID/GID 检查，26 项回归通过。发现现有旧 U-Boot 自身清单通过，但 build.sh 和 update_guard.c 输入 hash 不符合当前基线；未拿旧固件冒充当前产物，也未执行完整 U-Boot 构建。最终下载包需开发者当前固件构建后按文档绑定。

回应用户对操作文档的反馈，统一 fw/payload/pkg 三种输入角色，新增 `--all` 等价入口，明确整盘阶段只发送一次 system.sparse.img，另写 boot0 固件及启动配置。完整预检、正式执行、目标确认、读回、独立 eMMC 冷启动和板端只读核验都集中在 [FLASHING.md](../../../uboot/FLASHING.md)，不再仅列预检和操作表。

证据索引：`uboot/artifacts/busybox-validation-host-audit/collection.json`。当前只有主机证据，实际板卡写入、读回、自动冷启动及运行时输出仍为 pending；取得完整 UUU 与串口记录后才标记 U-Boot 板级验收通过。本轮没有重编 kernel/BusyBox、执行 SDK 完整构建、访问串口或写板。


## 2026-10-10 · 收拢 uboot 工作区与独立 eMMC 固件部署

按用户要求，将本轮 flash.py、package.py、tools、tests、layout.json、FLASHING.md 全部迁入 `uboot/`。04 根目录只保留里程碑文档和公共输出规则；固件源码快照与输出改为 `build/uboot/firmware/{src,out}`，下载包和临时检查集中 `build/uboot/`。本轮历史证据移至 `uboot/artifacts/r2-host-audit/`，原执行路径及输入记录保持历史身份，不当成新版本证据。

补上此前遗漏的 `uboot/flash.py bootloader`：只要求固件构建产物，不依赖 BR/kernel/rootfs 或新分区布局。只写 boot0 镜像范围及 eMMC 启动设置，读回 SHA-256 和 EXT_CSD；对整个实际 user area 与 boot0 非镜像范围做写前/写后比较。正式执行仍先主机 dry-run，再交互确认并固定 USB 路径。保留旧系统数据不代表新 U-Boot 可以自动引导旧布局，风险在操作说明中明确展示。

迁移后的 15 项回归通过，新增固件独立部署的 6 项测试通过，含真实 UUU -dry；新 guard 对象的交叉编译通过。没有执行完整构建、访问真实板卡或写入硬件。操作见 [uboot/FLASHING.md](../../../uboot/FLASHING.md)，证据索引为 `uboot/artifacts/bootloader-host-audit/collection.json`。产品 .imx 和实板冷启动/读回验收仍待开发者执行，issue 保持 open。


## 2026-10-10 · R2 U-Boot 与烧录封装交付

本轮按用户要求完成固件输入迁移和主机入口的软件实施，不扩大到 R1 BR 构建。04 的 `uboot/` 接管固定 revision、注册补丁、overlay 和构建脚本；02/03 及上游源码未修改。新配置提供 USB 下载自动 fastboot 与 eMMC p1 extlinux 两条路径，目标为 MMC 1 user area/p2 和 boot0 的 0x400 起点。

`uboot/package.py` 使用 genimage 组装镜像，根据 ext4 位图解释产生 AOSP Sparse，保留已分配块中的有意义零值；`uboot/flash.py` 封装 all/kernel/dtb/rootfs（rtfs 别名）。入口先做主机预检及真实 UUU -dry，正式执行仍要求交互确认并固定 USB 路径。板端只读 imx04 命令检查容量/布局/FAT 空间，写后核验写入块或文件的 SHA-256，并比较组件更新的受保护内容及 eMMC 启动配置。当前默认 p1 128 MiB、p2 2 GiB，由 uboot/layout.json 固定。

验证：配置生成、两个板级对象交叉编译、DTB 生成及 U-Boot ELF 链接通过。检查 dtbs 目标时，Make 自动带入了 U-Boot ELF 的编译和链接依赖（约 13 秒）；没有执行 build.sh build/all 或生成产品 .imx 下载包。主机整套 14 项测试通过，随后补充的独立 simg2img 解码互操作检查通过；测试使用合成固件、主机文件系统工具和假存储/UUU，真实 UUU 仅执行帮助及 -dry。

操作入口见 [uboot/FLASHING.md](../../../uboot/FLASHING.md)，证据索引为 `uboot/artifacts/r2-host-audit/collection.json`。本轮没有安装工具、修改主机网络、访问串口或执行真实板卡写操作。实际产品 .imx 构建、BR 产物接入、两条启动路径、USB 阶段切换、Sparse 实际传输量、读回及三个组件独立更新的冷启动验收仍待开发者完成；A2/A3 和整个 issue 保持 open。


## 2026-10-09 · R0 首轮目标对齐

已建立04工作区的issue/ADR/route。核对本地BR实际版本、固定源码身份、03的LCD/GT911/USB描述，以及host的网络管理方式。

用户已确认软件渲染、root空密码SSH认证、板端wt/PTY语义、Buildroot 集成与 Rust SDK，以及Weston IVI-shell和小型布局模块。

审查索引：`artifacts/2026-10-09-r0-audit/collection.json`。

本轮尚未修改02/03源码输入、执行SDK耗时构建、修改host网络配置或操作板卡。

## 2026-10-09 · S1、S2 路线修订

用户已确认自制主机烧录入口，并要求基于新 U-Boot 独立替换 kernel、DTB、rtfs。已修订 S1、S2 及 A2、A3，恢复 ADR-02、R2 的单行来源引用；具体设计集中维护于下方笔记。

用户进一步确认将基础 U-Boot 迁入 04 维护，并采用独立 p1 FAT32 启动分区＋p2 ext4 rootfs。归属已写入 ADR-01，布局及更新方法由集中笔记维护。

下一步先推进 R2 的基础固件迁移与主机入口，交付构建命令和通过 dry-run 的脚本；再接入 R1 的 BR 系统及 SDK。当前交付为修订后的需求和方案，源码迁移、固件修改、脚本与板端验收仍待实施。

[UUU 用法与主机烧录方案](../../../../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## 2026-10-09 · 锁定需求基线

用户要求提交 04 改动并锁定 issue。S1—S10、验收条件、输入归属及工作区内构建路径作为实施基线提交；issue 保持 open。03 已按用户确认的实物烧录与板上 shell 结果关闭，04 的 DRM/ECM 验收继续独立执行。下一步讨论 host 工具链安装与固定版本，再进入固件迁移和配置实施。

## 2026-10-09 · 主机工具链审查

基础依赖和原生 C/C++ 检查完成，Rust SDK 供应方式已按本地配方核实；结论及准备顺序见 [HOST_TOOLCHAIN.md](../../../HOST_TOOLCHAIN.md)。本轮未安装软件包、执行完整 SDK 构建或访问板卡。

用户随后通过 dnf 安装 genimage、dtc、gperf，主机路径与版本已核对，当前准备状态已更新到 HOST_TOOLCHAIN.md。

审查索引：`artifacts/2026-10-09-host-toolchain-audit/collection.json`。

## Buildroot 官方基线固定

用户确认采用官方 tag `2026.08` 及其依赖基线。本地 Buildroot 子模块已检出新建分支 `yceachan/2026.08-dev`，并推送至 GitHub `yceachan/buildroot-2025.02` 同名分支、设置 upstream；起点提交为 `d5180309b1b66ef3b8eaccca70ad69be8e0729a1`。`.gitmodules` 跟踪分支已同步，现有目录与 remote URL 保持稳定。

本地配方核对：Rust `1.97.1`、Qt `6.11.1`、Weston `15.0.1`。版本与 hash 使用该 tag 官方配方，external packages 另行固定发布版本及 Cargo.lock。选择与验证边界见 [ADR-01/05](adr.md)。本轮完成源码分支切换、GitHub 分支创建和文档同步；完整 BR 构建与 SDK 验证仍待实施。

## Qt Bridge 与 wt 职责对齐

用户确认使用 Qt Bridge for Rust，CXX 绑定及生成胶水对日常开发透明；wt 管理实例与命令生命周期，窗口 attach 与交互由后续独立 shell 管理。本轮由开机启动编排 launch 两个 GUI 并载入命令，Weston IVI-shell 固定左右 panel。

用户确认 busy 拒绝新命令、输出/result 回显调用端 PTY，以及创建独立会话使实例生命周期与调用端 SSH PTY 解耦。已同步 issue、ADR、route 与主机准备笔记。Qt Bridge for Rust 官方当前要求 Qt ≥ 6.10、Rust ≥ 1.88，已确认的 BR 官方基线满足这两项版本要求，ARMv7 交叉构建待验证。
