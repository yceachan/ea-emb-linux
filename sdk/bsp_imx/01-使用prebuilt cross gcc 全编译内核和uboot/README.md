# bear make

内核选 `imx_v6_v7_defconfig`，14×14 EVK 对应设备树是 `nxp/imx/imx6ull-14x14-evk.dtb`。U-Boot 选 `mx6ull_14x14_evk_defconfig`，与[官方板卡说明](https://docs.u-boot.org/en/stable/board/nxp/mx6ullevk.html)一致。

配置生成和 Bear 交叉 GCC 采集已验证，完整构建尚未执行。按下面顺序操作，每一步成功后再继续。

当前主机缺少 `gnutls-devel`，U-Boot 默认启用的主机工具 `mkeficapsule` 需要它。先安装：

```
pkexec /usr/bin/dnf install gnutls-devel
```

准备环境和输出目录。`/tmp` 是内存文件系统，因此编译产物放在 SDK 的磁盘目录。

这里把输出指定特定路径，便于保持源码树整洁，方便一套源码的复用适配不同板卡，而不会构建，config缓存打架。

```
cd /home/pi/ea-emb-linux
source profile/prebuilt.env
set -o pipefail

ksrc="$PWD/sdk/vendor_mainline/linux-7.2.9"
usrc="$PWD/sdk/vendor_mainline/uboot-2026.07"
kout="$PWD/sdk/bsp_imx/build/imx6ull-14x14-evk/kernel"
uout="$PWD/sdk/bsp_imx/build/imx6ull-14x14-evk/uboot"

mkdir -p "$kout" "$uout"
```

先编译内核。`mrproper` 清理指定输出目录，包括其中的 `.config`；随后重新生成配置，保证这次是完整编译。`all` 会构建内核镜像、已配置的模块和设备树：

```
make -C "$ksrc" O="$kout" mrproper
make -C "$ksrc" O="$kout" imx_v6_v7_defconfig

bear --output "$kout/compile_commands.json" -- \
    make -C "$ksrc" O="$kout" -j4 all \
    2>&1 | tee "$kout/build.log"
```

内核成功后，再完整编译 U-Boot：

```
make -C "$usrc" O="$uout" mrproper
make -C "$usrc" O="$uout" mx6ull_14x14_evk_defconfig

bear --output "$uout/compile_commands.json" -- \
    make -C "$usrc" O="$uout" -j4 all \
    2>&1 | tee "$uout/build.log"
```

检查主要产物：

```
ls -lh \
    "$kout/vmlinux" \
    "$kout/arch/arm/boot/zImage" \
    "$kout/arch/arm/boot/dts/nxp/imx/imx6ull-14x14-evk.dtb" \
    "$uout/u-boot" \
    "$uout/u-boot-dtb.imx"
```

两个工程分别保留自己的 `compile_commands.json`。检查采集条目数：

```
python3 - "$kout/compile_commands.json" "$uout/compile_commands.json" <<'PY'
import json
import sys

for path in sys.argv[1:]:
    with open(path) as stream:
        entries = json.load(stream)
    if not entries:
        raise SystemExit(f"编译命令为空：{path}")
    print(f"{path}: {len(entries)} 条")
PY
```

Bear 只记录实际发生的编译，所以首次完整采集需要从清理后的输出目录开始。后续普通增量构建直接运行 `make`；如果要继续补充数据库，使用 `bear --append --output … -- make …`。参见 [Bear 3.1.6 说明](https://github.com/rizsotto/Bear/blob/3.1.6/README.md)。

# clangd

`--compile-commands-dir` 只能指定一个目录，但同一个 clangd 可以按源码目录使用两份数据库。每个源文件使用对应的编译命令，两份数据库的参数不会叠加。[配置说明](https://clangd.llvm.org/config#compilationdatabase)

你的场景可以取消全局 `--compile-commands-dir`，分别配置。

在内核源码根目录的 `.clangd` 中，指向内核构建目录：

```
CompileFlags:
  CompilationDatabase: /home/pi/ea-emb-linux/sdk/bsp_imx/build/imx6ull-14x14-evk/kernel
```

在树外模块根目录的 `.clangd` 中，如果模块数据库也放在那里：

```
CompileFlags:
  CompilationDatabase: .
```

这样，打开内核源码时使用内核数据库，打开模块源码时使用模块数据库。

模块通过 Kbuild 编译时，自己的数据库已经记录了内核源码头文件、$kout 中生成的头文件，以及模块专用的宏和参数。因此，解析模块不需要再“继承”内核数据库。内核数据库主要用于准确分析内核自身的源码。[编译命令说明](https://clangd.llvm.org/design/compile-commands)