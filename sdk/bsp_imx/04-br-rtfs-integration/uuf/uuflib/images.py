"""Strict package/image primitives. No USB access or target writes in this module."""
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import struct

BLOCK = 4096
WINDOW = 4 * 1024 * 1024
BUFFER = 16 * 1024 * 1024
RAW, FILL, SKIP = 0xCAC1, 0xCAC2, 0xCAC3


from .process import command

def sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


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
                    or not blocks or blocks > 0xffffffff // 8 or not 0 < chunks <= (length - 28) // 12):
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


