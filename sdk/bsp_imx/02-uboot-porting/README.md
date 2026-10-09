# 00 · 工作区布局与文档索引

本目录保存 100ask i.MX6ULL Pro 的 U-Boot 板级移植输入、主机操作脚本和验证记录。上游源码位于 `sdk/vendor_mainline/uboot-2026.07/`，独立构建目录位于 `sdk/bsp_imx/build/`。

README 只维护布局和文档入口。文档编号与文件名保持稳定；下载与烧录说明集中维护，查板级验收结果时阅读 06。

## 文档索引

| 编号 | 文档 | 负责的内容 |
|---|---|---|
| 00 | [README.md](README.md) | 工作区布局、文档顺序和文件入口 |
| 01 | [PORTING.md](PORTING.md) | 板型注册、ROM 镜像、板级代码、设备树和配置设计 |
| 03 | [RAM_BOOT.md](RAM_BOOT.md) | 源码快照构建、vendor Linux 手工启动和诊断命令 |
| 06 | [STATUS.md](STATUS.md) | 已通过的验收项、未验证项和历史证据入口 |

[UUU 用法与主机烧录方案](../../../notes/imx_toolkit/uuu的用法和一些已知限制与host脚本集成方案.md)

## 本目录的布局

| 路径 | 用途 | 维护位置 |
|---|---|---|
| [overlay/](overlay/) | 本板新增的源码、设备树、配置和头文件，按上游目录结构覆盖 | 本目录 |
| [register-board.patch](register-board.patch) | 注册板型，并修改共享 MXC 串口驱动的波特率计算 | 本目录 |
| [base-revision](base-revision) | 固定构建使用的上游 Git 提交 | 本目录 |
| [build.sh](build.sh) | 生成独立源码快照、配置、镜像和校验清单 | 本目录 |
| [uboot.py](uboot.py) | 主机工具入口 | 本目录 |
| [ram-boot.uuu](ram-boot.uuu) | 命令列表输入 | 本目录 |
| [emmc-flash.uuu](emmc-flash.uuu) | 命令列表输入 | 本目录 |
| [tests/](tests/) | 主机工具测试 | 本目录 |
| `artifacts/` | 最近一次构建交付的镜像、配置、脚本和校验清单 | `build.sh build` 生成 |
| `logs/` | 主机工具运行记录 | `uboot.py` 生成 |
| `evidence/` | 按实验归档的镜像、日志、来源索引和校验清单 | 实验归档 |

`overlay/` 与补丁是移植源码的维护入口。构建快照中的修改不会自动回写到这里。`artifacts/` 和 `logs/` 不纳入 Git，不能用它们代替长期证据。

## 外部源码与构建目录

| 路径 | 与本工作区的关系 |
|---|---|
| [../../vendor_mainline/uboot-2026.07/](../../vendor_mainline/uboot-2026.07/) | 上游源码仓库，由 `base-revision` 选择提交 |
| `../build/`下的本板构建目录 | 保存 `src/` 源码快照、`out/` 编译结果和构建日志 |
| [../../../profile/prebuilt.env](../../../profile/prebuilt.env) | 提供构建使用的工具链环境 |

每轮构建的 `src/` 来自上游提交、`overlay/` 和补丁。`out/` 记录生成配置、源码提交和输入校验清单。修改移植输入后，使用新的构建目录，具体命令由 03 号文档维护。
