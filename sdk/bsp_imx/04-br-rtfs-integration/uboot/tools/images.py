"""Strict package/image primitives. No USB access or target writes in this module."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess

BLOCK = 4096
WINDOW = 4 * 1024 * 1024
BUFFER = 16 * 1024 * 1024
DTB = "imx6ull-100ask-pro.dtb"
BOOTCONF = ("DEFAULT imx\nTIMEOUT 0\nLABEL imx\n"
            "  LINUX /zImage\n  FDT /imx6ull-100ask-pro.dtb\n"
            "  APPEND console=ttymxc0,1500000 root=/dev/mmcblk1p2 rootwait rw\n")
REQUIRED = {"layout.json", "loader.imx", "product.imx", "zImage", DTB,
            "extlinux.conf", "system.sparse.img", "rootfs.sparse.img", "firmware.json",
            "uboot.config", "uboot-inputs.sha256", "source-revision"}
RAW, FILL, SKIP = 0xCAC1, 0xCAC2, 0xCAC3


def command(argv, *, cwd=None, timeout=120):
    result = subprocess.run([str(x) for x in argv], cwd=cwd, capture_output=True,
                            timeout=timeout, env=dict(os.environ, LC_ALL="C"))
    if result.returncode:
        raise ValueError(f"命令失败：{argv}\n{result.stdout.decode(errors='replace')}"
                         f"{result.stderr.decode(errors='replace')}")
    return result.stdout.decode(errors="replace")


def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def layout(path):
    value = json.loads(Path(path).read_text())
    if (set(value) != {"schema", "board", "sector_size", "sparse_block_size", "p1", "p2"}
            or value["schema"] != 1 or value["board"] != "100ask-imx6ull-pro"
            or value["sector_size"] != 512 or value["sparse_block_size"] != BLOCK):
        raise ValueError("不支持的板卡或布局格式")
    end = 8
    for key, kind in (("p1", 12), ("p2", 131)):
        part = value[key]
        if (set(part) != {"start", "sectors", "type"} or part["type"] != kind
                or any(type(part[x]) is not int or part[x] <= 0
                       or part[x] % 8 for x in ("start", "sectors"))
                or part["start"] < end):
            raise ValueError(f"无效的 {key} 起点、容量或类型")
        end = part["start"] + part["sectors"]
    # Fixed board has a ~3.6 GiB user area; runtime guard checks actual capacity.
    if end > 7500000 or value["p1"]["sectors"] < 131072:
        raise ValueError("布局超出本板容量，或 FAT32 启动分区过小")
    return value


def ext4_allocated(path):
    """Use e2fsprogs' block bitmap interpretation, never zero-content heuristics."""
    command(["e2fsck", "-fn", path])
    text = command(["dumpe2fs", "-f", path])
    header, groups = text.split("Group 0:", 1)
    def field(name):
        match = re.search(rf"^{name}:\s+(\d+)\s*$", header, re.M)
        if match is None:
            raise ValueError(f"ext4 缺少字段：{name}")
        return int(match[1])
    count, size, free_count = field("Block count"), field("Block size"), field("Free blocks")
    if size != BLOCK or count * size != Path(path).stat().st_size:
        raise ValueError("rootfs 必须为 4096 字节块且文件长度等于文件系统容量")
    free = []
    for line in re.findall(r"^[ \t]+Free blocks:[ \t]*([^\n]*)", groups, re.M):
        # Empty per-group free lists are valid.
        for token in line.strip().split(","):
            token = token.strip()
            if not token:
                continue
            match = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
            if match is None:
                raise ValueError(f"不能解析 ext4 空闲块：{token}")
            a, b = int(match[1]), int(match[2] or match[1]) + 1
            if not 0 <= a < b <= count:
                raise ValueError("ext4 空闲块超出容量")
            free.append((a, b))
    free.sort()
    if sum(b - a for a, b in free) != free_count:
        raise ValueError("ext4 空闲块清单与 superblock 计数不一致")
    allocated, cursor = [], 0
    for a, b in free:
        if a < cursor:
            raise ValueError("ext4 空闲块清单重叠")
        if a > cursor:
            allocated.append((cursor, a))
        cursor = b
    if cursor < count:
        allocated.append((cursor, count))
    return count, allocated


@dataclass(frozen=True)
class Chunk:
    kind: int
    start: int  # blocks, not bytes
    blocks: int
    offset: int  # payload position in sparse file

    @property
    def end(self):
        return self.start + self.blocks


class Sparse:
    def __init__(self, path):
        self.path = Path(path)
        self.chunks = []
        length = self.path.stat().st_size
        with self.path.open("rb") as stream:
            head = stream.read(28)
            if len(head) != 28:
                raise ValueError("Sparse header 截断")
            magic, major, minor, fh, ch, bs, blocks, chunks, crc = struct.unpack("<I4H4I", head)
            if (magic != 0xED26FF3A or (major, minor, fh, ch, bs, crc) != (1, 0, 28, 12, BLOCK, 0)
                    or not blocks or blocks > 7500000 // 8 or not 0 < chunks <= (length - 28) // 12):
                raise ValueError("不支持或非法的 Sparse header")
            cursor = 0
            for _ in range(chunks):
                head = stream.read(12)
                if len(head) != 12:
                    raise ValueError("Sparse chunk 截断")
                kind, reserved, n, total = struct.unpack("<2H2I", head)
                payload = {RAW: n * BLOCK, FILL: 4, SKIP: 0}.get(kind)
                if (reserved or not n or payload is None or total != payload + 12
                        or cursor + n > blocks or stream.tell() + payload > length):
                    raise ValueError("Sparse chunk 大小、类型或写入范围非法")
                self.chunks.append(Chunk(kind, cursor, n, stream.tell()))
                stream.seek(payload, 1)
                cursor += n
            if cursor != blocks or stream.tell() != length:
                raise ValueError("Sparse 展开容量或尾部数据不一致")
        self.blocks = blocks

    def data(self, stream, chunk, byte_offset, size):
        if chunk.kind == RAW:
            stream.seek(chunk.offset + byte_offset)
            result = stream.read(size)
            if len(result) != size:
                raise ValueError("Sparse payload 截断")
            return result
        if chunk.kind == FILL:
            stream.seek(chunk.offset)
            return stream.read(4) * (size // 4)
        return bytes(size)

    def extract(self, path, start=0, blocks=None):
        """Expand a range into a host sparse file; target is never accessed."""
        blocks = self.blocks - start if blocks is None else blocks
        if start < 0 or blocks <= 0 or start + blocks > self.blocks:
            raise ValueError("展开范围超界")
        with self.path.open("rb") as src, Path(path).open("xb") as dst:
            dst.truncate(blocks * BLOCK)
            for c in self.chunks:
                a, b = max(c.start, start), min(c.end, start + blocks)
                if a >= b or c.kind == SKIP:
                    continue
                for block in range(a, b, WINDOW // BLOCK):
                    n = min(b - block, WINDOW // BLOCK) * BLOCK
                    dst.seek((block - start) * BLOCK)
                    dst.write(self.data(src, c, (block - c.start) * BLOCK, n))

    def covers(self, ranges):
        skipped = [c for c in self.chunks if c.kind == SKIP]
        return all(not any(c.start < b and c.end > a for c in skipped) for a, b in ranges)

    def checks(self, lba_base=0):
        """Bound readback commands to 4 MiB; include meaningful zero/FILL data."""
        with self.path.open("rb") as stream:
            for c in self.chunks:
                if c.kind == SKIP:
                    continue
                for offset in range(0, c.blocks * BLOCK, WINDOW):
                    n = min(WINDOW, c.blocks * BLOCK - offset)
                    digest = hashlib.sha256(self.data(stream, c, offset, n)).hexdigest()
                    yield lba_base + c.start * 8 + offset // 512, n // 512, digest

    def summary(self):
        return {"logical_bytes": self.blocks * BLOCK,
                "container_bytes": self.path.stat().st_size,
                "written_bytes": sum(c.blocks * BLOCK for c in self.chunks if c.kind != SKIP),
                "skipped_bytes": sum(c.blocks * BLOCK for c in self.chunks if c.kind == SKIP),
                "chunks": len(self.chunks)}


def encode_sparse(source, target, blocks, allocated):
    """Allocation-aware AOSP Sparse: zero allocated data is FILL, never SKIP."""
    parts, cursor = [], 0
    for a, b in allocated:
        if not cursor <= a < b <= blocks:
            raise ValueError("有效块范围无效或重叠")
        if cursor < a:
            parts.append((SKIP, cursor, a))
        for start in range(a, b, WINDOW // BLOCK):
            parts.append((RAW, start, min(start + WINDOW // BLOCK, b)))
        cursor = b
    if cursor < blocks:
        parts.append((SKIP, cursor, blocks))
    with Path(source).open("rb") as src, Path(target).open("xb") as dst:
        dst.write(struct.pack("<I4H4I", 0xED26FF3A, 1, 0, 28, 12, BLOCK, blocks, len(parts), 0))
        for kind, a, b in parts:
            data = b""
            if kind != SKIP:
                src.seek(a * BLOCK)
                data = src.read((b - a) * BLOCK)
                if len(data) != (b - a) * BLOCK:
                    raise ValueError("raw 输入截断")
                if data == data[:4] * (len(data) // 4):
                    kind, data = FILL, data[:4]
            dst.write(struct.pack("<2H2I", kind, 0, b - a, len(data) + 12))
            dst.write(data)


def verify_sums(folder, required=REQUIRED):
    folder = Path(folder)
    records = {}
    for line in (folder / "SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)", line)
        if match is None or match[2] in records:
            raise ValueError("SHA256SUMS 含非法路径、重复或非法记录")
        digest, name = match.groups()
        if name in {".", "..", "SHA256SUMS"}:
            raise ValueError("非法清单文件名")
        file = folder / name
        if file.is_symlink() or not file.is_file() or sha256(file) != digest:
            raise ValueError(f"校验和不符或输入不安全：{name}")
        records[name] = digest
    if not required <= records.keys():
        raise ValueError(f"校验清单缺少：{sorted(required - records.keys())}")
    return records


def write_sums(folder):
    folder = Path(folder)
    (folder / "SHA256SUMS").write_text("".join(
        f"{sha256(p)}  {p.name}\n" for p in sorted(folder.iterdir()) if p.is_file()))


def validate_imx(folder):
    folder = Path(folder)
    for name in ("loader.imx", "product.imx"):
        path = folder / name
        with path.open("rb") as stream:
            head = stream.read(4)
        if (not 4096 <= path.stat().st_size <= 0xFFC00 or path.stat().st_size % 512
                or head != b"\xd1\x00\x20\x40"):
            raise ValueError("U-Boot .imx IVT/长度非法")
    if sha256(folder / "loader.imx") != sha256(folder / "product.imx"):
        raise ValueError("本轮 loader 与产品必须绑定同一份 04 固件")


def validate_files(folder):
    folder = Path(folder)
    for name in ("zImage", DTB):
        path = folder / name
        size = path.stat().st_size
        if not 40 <= size <= BUFFER:
            raise ValueError(f"{name} 长度超出下载缓冲区或过短")
        with path.open("rb") as stream:
            head = stream.read(40)
        if name == "zImage" and head[36:40] != struct.pack("<I", 0x016F2818):
            raise ValueError("不是 ARM zImage")
        if name == DTB and (head[:4] != b"\xd0\x0d\xfe\xed" or struct.unpack(">I", head[4:8])[0] != size):
            raise ValueError("DTB magic/长度不正确")
    command(["dtc", "-I", "dtb", "-O", "dts", "-o", os.devnull, folder / DTB])
    validate_imx(folder)
    if (folder / "extlinux.conf").read_text() != BOOTCONF:
        raise ValueError("启动参数或文件路径偏离 04 基线")


def preflight_images(folder, scratch, config):
    """Validate FS structure and allocation coverage, including zero metadata."""
    folder, scratch = Path(folder), Path(scratch)
    system, rootfs = Sparse(folder / "system.sparse.img"), Sparse(folder / "rootfs.sparse.img")
    p1, p2 = config["p1"], config["p2"]
    if system.blocks * 8 != p2["start"] + p2["sectors"] or rootfs.blocks * 8 != p2["sectors"]:
        raise ValueError("整盘或 rootfs 展开容量与布局不一致")
    if not system.covers([(0, 1), (p1["start"] // 8, (p1["start"] + p1["sectors"]) // 8)]):
        raise ValueError("分区表或 FAT 中含 DONT_CARE")
    system.extract(scratch / "mbr", 0, 1)
    mbr = (scratch / "mbr").read_bytes()[:512]
    if mbr[510:] != b"\x55\xaa" or any(mbr[478:510]):
        raise ValueError("MBR 签名、额外分区无效")
    for index, p in enumerate((p1, p2)):
        boot, _, kind, _, start, sectors = struct.unpack("<B3sB3sII", mbr[446 + 16 * index:462 + 16 * index])
        if (boot, kind, start, sectors) != (128 if index == 0 else 0, p["type"], p["start"], p["sectors"]):
            raise ValueError("MBR 与布局不一致")
    system.extract(scratch / "boot.fat", p1["start"] // 8, p1["sectors"] // 8)
    command(["fsck.fat", "-n", scratch / "boot.fat"])
    for name, target in (("zImage", "zImage"), (DTB, DTB), ("extlinux.conf", "extlinux/extlinux.conf")):
        dest = scratch / name
        command(["mcopy", "-i", scratch / "boot.fat", f"::{target}", dest])
        if sha256(dest) != sha256(folder / name):
            raise ValueError(f"整盘 p1 的 {name} 与组件不一致")
    rootfs.extract(scratch / "rootfs.ext4")
    _, allocated = ext4_allocated(scratch / "rootfs.ext4")
    if not rootfs.covers(allocated):
        raise ValueError("rootfs 的已分配块被错误跳过（含有意义的零值）")
    shifted = [(a + p2["start"] // 8, b + p2["start"] // 8) for a, b in allocated]
    if not system.covers(shifted):
        raise ValueError("整盘跳过了 rootfs 已分配块")
    if list(rootfs.checks(p2["start"])) != [x for x in system.checks() if x[0] >= p2["start"]]:
        raise ValueError("整盘 p2 与独立 rootfs Sparse 内容/块映射不一致")
    return system, rootfs
