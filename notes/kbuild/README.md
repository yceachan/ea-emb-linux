# 内核构建产物与树外模块

本文以本工程的 i.MX6ULL 14×14 EVK 构建为例。内核使用 `imx_v6_v7_defconfig`，源码与编译产物分开放置。构建产物同时用于板卡启动、树外模块编译和 clangd 代码分析，各用途需要保留的文件不同。

## 源码目录与输出目录

`ksrc` 是内核源码目录。`kout` 是通过 `O=` 指定的内核输出目录。这两个名称只是本文使用的 Shell 变量，不需要导出。

```bash
source /home/pi/ea-emb-linux/profile/prebuilt.env

ksrc=/home/pi/ea-emb-linux/sdk/vendor_mainline/linux-7.2.9
kout=/home/pi/ea-emb-linux/sdk/bsp_imx/build/imx6ull-14x14-evk/kernel
```

源码目录保存内核的 `.c`、`.h`、Kconfig、Makefile 和设备树源码。输出目录保存本次配置、生成文件、目标文件和镜像。后续调用 Make 时，继续使用相同的 `O="$kout"`，才能使用本次构建状态。

| 目录 | 内容 | 使用方式 |
| --- | --- | --- |
| `$ksrc` | 原始内核源码与构建规则 | 编译、修改和阅读内核源码 |
| `$kout` | 本次 ARM 内核的配置与产物 | 增量构建、编译板卡模块和分析代码 |
| `/usr/src/kernels/7.2.7-200.fc44.x86_64` | Fedora 主机内核的开发文件 | 编译匹配该 x86_64 主机内核的模块 |

Fedora 的目录对应主机架构、主机配置和主机内核版本。板卡模块使用本次 ARM 内核的构建目录。两个目录不能互换。

## 配置如何变成产物

`defconfig` 是配置模板，记录选定的配置项。Kconfig 读取模板、补齐默认值，并处理配置项之间的依赖关系，生成完整的 `.config`。后续编译按 `.config` 决定哪些功能内置、哪些功能生成模块，以及哪些功能不参与构建。

```bash
# 生成配置。
make -C "$ksrc" O="$kout" imx_v6_v7_defconfig

# 完整构建当前配置，并采集实际发生的编译命令。
set -o pipefail
bear --output "$kout/compile_commands.json" -- \
    make -C "$ksrc" O="$kout" -j12 all \
    2>&1 | tee "$kout/build.log"
```

在本次 ARM 配置下，`all` 包含内核镜像、配置为模块的驱动和配置支持的设备树。Bear 执行 Make 并记录编译器调用。构建失败时也可能留下部分数据库，因此 JSON 文件存在不能证明镜像构建成功。

## 镜像、模块与符号文件

下表中的路径都相对于 `$kout`。设备树文件用于描述板卡硬件。ELF 是保存机器代码、段信息和符号信息的文件格式。

| 产物 | 内容 | 用途 |
| --- | --- | --- |
| `vmlinux` | 链接完成的内核 ELF 文件 | 分析内核符号、反汇编和调试 |
| `arch/arm/boot/Image` | 从内核 ELF 提取的未压缩二进制镜像 | ARM 镜像构建的中间产物，也供支持该格式的启动流程使用 |
| `arch/arm/boot/zImage` | 压缩内核与 ARM 启动、解压代码 | 本次板卡启动使用的内核镜像 |
| `arch/arm/boot/dts/nxp/imx/imx6ull-14x14-evk.dtb` | 编译后的 EVK 设备树 | 与内核一起交给启动程序 |
| 各子目录中的 `*.ko` | 配置为模块的驱动或其他内核功能 | 安装到板卡根文件系统，供运行时加载 |
| `System.map` | 内核符号与地址的映射 | 查询符号地址、辅助分析日志 |
| `Module.symvers` | 内核及已构建模块导出的符号、版本校验值等 | 树外模块的符号检查与版本匹配 |
| `modules.order` | 模块在 Makefile 中出现的顺序 | 帮助 `modprobe` 确定模块别名的解析顺序 |
| `modules.builtin` | 内置于内核的模块名称 | 帮助 `modprobe` 识别已内置的功能 |
| `modules.builtin.modinfo` | 内置模块的元信息 | 提供内置模块的属性信息 |

本次构建启用了 `CONFIG_MODULES=y` 和 `CONFIG_MODVERSIONS=y`。`CONFIG_MODVERSIONS` 使用导出符号接口的校验值检查模块兼容性，因此树外模块需要匹配本次内核构建的 `Module.symvers`。当前配置还启用了 `CONFIG_DEBUG_INFO_NONE=y`，所以 `vmlinux` 有符号信息，但没有完整的 DWARF 源码调试信息。

完整构建会生成当前配置支持的多个 DTB。板卡启动时选择 EVK 对应的 DTB。内置驱动已经进入内核镜像，不会为该内置配置额外生成可加载的 `.ko`。

构建完成后，可以查看主要文件与实际内核版本。版本包含源码版本及本次构建得到的后缀，以生成文件为准。

```bash
cat "$kout/include/config/kernel.release"
ls -lh \
    "$kout/vmlinux" \
    "$kout/arch/arm/boot/zImage" \
    "$kout/arch/arm/boot/dts/nxp/imx/imx6ull-14x14-evk.dtb" \
    "$kout/Module.symvers"
```

模块需要另外安装到板卡的根文件系统暂存目录。下面的命令在用户指定的 `rootfs` 中安装模块，不向主机的 `/lib/modules` 安装。安装位置是 `$rootfs/lib/modules/<kernel.release>/`，其中版本来自本次内核构建。

```bash
# 将该路径替换为实际的板卡根文件系统暂存目录。
rootfs=/tmp/imx6ull-rootfs
make -C "$ksrc" O="$kout" INSTALL_MOD_PATH="$rootfs" modules_install
```

## 为什么输出目录的 include 不完整

内核编译同时使用源码中的头文件和构建时生成的头文件。源码中的头文件定义内核接口，生成文件描述当前架构、配置和构建结果。只复制 `$kout/include`，不能得到完整的模块编译环境。

| 位置 | 主要内容 |
| --- | --- |
| `$ksrc/include/linux/` 等目录 | 内核通用接口与类型定义，例如 `linux/module.h` |
| `$ksrc/arch/arm/include/` | ARM 架构的接口定义 |
| `$kout/include/config/` | Kconfig 生成的 Make 配置 `auto.conf`、内核版本及配置依赖信息 |
| `$kout/include/generated/` | 配置宏 `autoconf.h`、版本头文件、结构体偏移等生成文件 |
| `$kout/arch/arm/include/generated/` | ARM 架构构建时生成的头文件 |

这些生成文件来自本次构建，不要手工修改。修改配置时使用 Kconfig 目标，例如 `make -C "$ksrc" O="$kout" menuconfig`。重新编译后，Kbuild 会更新对应的生成文件。

用户空间程序使用另一类头文件：UAPI，即内核向用户空间提供的接口。它们由 `headers_install` 导出，并经过处理以供用户空间使用。导出的 UAPI 头文件不包含完整的内核内部接口，也不能替代树外模块的 Kbuild 环境。

```bash
make -C "$ksrc" O="$kout" \
    INSTALL_HDR_PATH=/tmp/imx6ull-uapi headers_install
# 导出结果位于 /tmp/imx6ull-uapi/include/。
```

普通用户空间交叉编译通常使用工具链 sysroot 中已经配套的 libc 和 UAPI 头文件。需要更新用户空间头文件时，再单独处理导出和 sysroot 集成。

## KDIR 指向哪里

`KDIR` 是树外模块 Makefile 常用的变量名，不是内核固定要求的环境变量。它可以表示源码目录，也可以表示已构建的内核输出目录，具体取决于 Make 的调用方式。源码和输出分开时，需要让 Kbuild 同时知道这两个位置。

在树外模块目录中执行下面任意一种方式。当前目录必须包含模块的 Kbuild 或 Makefile，且已经加载本文开头的交叉编译环境。

```bash
# 方式一：KDIR 表示源码目录，同时提供 O=。
KDIR="$ksrc"
make -C "$KDIR" O="$kout" M="$PWD" modules

# 方式二：KDIR 表示内核输出目录。
KDIR="$kout"
make -C "$KDIR" M="$PWD" modules
```

`M=` 指定树外模块的源码目录。没有单独指定模块输出目录时，模块产物写入该目录。Kbuild 自动加入内核源码头文件和生成头文件的搜索路径。

第二种方式通过 `$kout/Makefile` 工作。这个 Makefile 是自动生成的入口，它设置 `KBUILD_OUTPUT`，再引用 `$ksrc/Makefile`。因此，使用输出目录作为入口仍然需要原始源码目录存在。

给 Fedora 主机编译模块时，常见入口是 `/lib/modules/$(uname -r)/build`。当前主机的这个链接指向 `/usr/src/kernels/7.2.7-200.fc44.x86_64`。给板卡编译模块时，使用 ARM 构建入口和交叉工具链，不使用主机入口。

`modules_prepare` 能生成编译模块所需的部分准备文件，但不会生成 `Module.symvers`。本次启用了模块版本校验，所以完整内核构建提供的符号表需要保留。

## Bear、clangd 与清理操作

`compile_commands.json` 保存实际编译过的源文件、工作目录、编译器及参数。`build.log` 是 `tee` 保存的日志。这两个文件用于开发和检查，板卡启动不需要它们。

数据库可以放在 `$kout` 中。clangd 根据记录里的工作目录解析相对路径，数据库文件所在位置不会改变这些路径。使用时需要保留对应源码、生成头文件以及所需的工具链环境。

```bash
clangd --compile-commands-dir="$kout"
```

树外模块采集自己的数据库，因为模块有自己的源码和编译参数。在模块目录执行以下命令；如果此前已经完成模块编译，需要先清理模块产物，才能重新采集全部编译命令。

```bash
# 仅清理当前树外模块的构建产物。
make -C "$kout" M="$PWD" clean

bear --output "$PWD/compile_commands.json" -- \
    make -C "$kout" M="$PWD" modules
```

构建失败后续编时，使用 `bear --append --output … -- make …`，保留已经采集的记录。更换架构、内核配置或源码路径后，重新构建并生成数据库，避免继续使用旧记录。数据库只记录命令，不包含头文件或源码的副本。

| 操作 | 对本次内核输出目录的影响 |
| --- | --- |
| `make -C "$ksrc" O="$kout" clean` | 删除大部分构建产物，保留 `.config` 和外部模块构建需要的准备文件；本源码版本也会删除 `compile_commands.json` |
| `make -C "$ksrc" O="$kout" mrproper` | 在 `clean` 基础上删除 `.config`、生成的配置与头文件、`Module.symvers` 等，需要重新配置 |
| 清空整个 `$kout` | 同时丢失本次配置、镜像、符号表、生成文件、日志和数据库 |

运行 `mrproper` 或清空输出目录前，先保存需要保留的配置。保留源码与完整输出目录，才能继续使用当前模块构建环境。若输出位于 tmpfs，重启或卸载 tmpfs 会丢失这些文件；只把 JSON 复制到磁盘不能保存完整的 clangd 解析环境。

本文的目录结构和清理行为以本地 `linux-7.2.9` 源码及当前构建结果为准。对应说明可查阅 [树外模块文档](/home/pi/ea-emb-linux/sdk/vendor_mainline/linux-7.2.9/Documentation/kbuild/modules.rst)、[Kbuild 产物说明](/home/pi/ea-emb-linux/sdk/vendor_mainline/linux-7.2.9/Documentation/kbuild/kbuild.rst)、[UAPI 头文件导出说明](/home/pi/ea-emb-linux/sdk/vendor_mainline/linux-7.2.9/Documentation/kbuild/headers_install.rst)和[内核 Makefile 的清理规则](/home/pi/ea-emb-linux/sdk/vendor_mainline/linux-7.2.9/Makefile:1730)。
