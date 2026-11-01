"""最小 NBT 读取器（只读，不写盘）。round-171（P1，世界地图 / 投影共用底层）。

只实现「读」：标签类型 0–12（End / Byte / Short / Int / Long / Float / Double /
ByteArray / String / List / Compound / IntArray / LongArray）。输入支持 gzip
（`.litematic`、`.mca` 内区块）、zlib（`.mca` 区块压缩类型 2）与未压缩数据。

安全红线（解析恶意 / 损坏文件不得吃满内存）：

- 递归深度 ≤ ``MAX_DEPTH``；
- 单个数组元素 ≤ ``MAX_ARRAY``；
- 解压后字节 ≤ ``MAX_BYTES``（流式限制，不会先炸内存再判断）。

解析全部是纯 Python（不引入 nbtlib）；方块数组解码见
``unpack_long_array``，被 ``schematic`` / ``world_map`` 共用。
"""
from __future__ import annotations

import zlib
from array import array

MAX_DEPTH = 64
MAX_ARRAY = 8 * 1024 * 1024          # 单个数组元素上限
MAX_BYTES = 512 * 1024 * 1024        # 单文件解压后上限

TAG_END = 0
TAG_BYTE = 1
TAG_SHORT = 2
TAG_INT = 3
TAG_LONG = 4
TAG_FLOAT = 5
TAG_DOUBLE = 6
TAG_BYTE_ARRAY = 7
TAG_STRING = 8
TAG_LIST = 9
TAG_COMPOUND = 10
TAG_INT_ARRAY = 11
TAG_LONG_ARRAY = 12

_MASK64 = (1 << 64) - 1


class NbtError(ValueError):
    """NBT 数据损坏，或触发了安全上限。"""


def inflate(data: bytes) -> bytes:
    """按魔数解压 gzip / zlib；未压缩数据原样返回（带安全上限）。"""
    if not data:
        raise NbtError("空数据")
    if data[:2] == b"\x1f\x8b":
        wbits = 31          # gzip
    elif data[:1] == b"\x78":
        wbits = 15          # zlib
    else:
        if len(data) > MAX_BYTES:
            raise NbtError("未压缩数据超过上限")
        return data
    d = zlib.decompressobj(wbits)
    out = bytearray()
    buf = data
    try:
        while True:
            room = MAX_BYTES + 1 - len(out)
            if room <= 0:
                raise NbtError(
                    "解压后超过 %d MB 上限" % (MAX_BYTES // 1024 // 1024))
            chunk = d.decompress(buf, room)
            out += chunk
            if len(out) > MAX_BYTES:
                raise NbtError(
                    "解压后超过 %d MB 上限" % (MAX_BYTES // 1024 // 1024))
            buf = d.unconsumed_tail
            if not buf:
                break
    except zlib.error as e:
        raise NbtError("解压失败：%s" % e) from e
    if not out:
        raise NbtError("解压结果为空")
    return bytes(out)


class _Reader:
    """游标式 NBT 解析器（一次性读完，不支持流式大文件）。"""

    __slots__ = ("b", "i", "n")

    def __init__(self, data: bytes):
        self.b = data
        self.i = 0
        self.n = len(data)

    def _take(self, k: int) -> int:
        if k < 0 or self.i + k > self.n:
            raise NbtError("数据不完整（偏移 %d）" % self.i)
        start = self.i
        self.i += k
        return start

    def _u8(self) -> int:
        return self.b[self._take(1)]

    def _i8(self) -> int:
        v = self.b[self._take(1)]
        return v - 256 if v >= 128 else v

    def _i16(self) -> int:
        s = self._take(2)
        v = int.from_bytes(self.b[s:s + 2], "big", signed=True)
        return v

    def _u16(self) -> int:
        s = self._take(2)
        return int.from_bytes(self.b[s:s + 2], "big")

    def _i32(self) -> int:
        s = self._take(4)
        return int.from_bytes(self.b[s:s + 4], "big", signed=True)

    def _i64(self) -> int:
        s = self._take(8)
        return int.from_bytes(self.b[s:s + 8], "big", signed=True)

    def _f32(self) -> float:
        s = self._take(4)
        return _f32(self.b[s:s + 4])

    def _f64(self) -> float:
        s = self._take(8)
        return _f64(self.b[s:s + 8])

    def _str(self) -> str:
        n = self._u16()
        if n > 65535:
            raise NbtError("字符串长度非法")
        s = self._take(n)
        try:
            return self.b[s:s + n].decode("utf-8", "replace")
        except UnicodeDecodeError as e:  # pragma: no cover - replace 已兜底
            raise NbtError("字符串解码失败：%s" % e) from e

    def _array_len(self) -> int:
        n = self._i32()
        if n < 0 or n > MAX_ARRAY:
            raise NbtError("数组长度超出上限：%d" % n)
        return n

    def payload(self, tag: int, depth: int):
        """读取一个「无名称」的标签负载（List 元素用）。"""
        if tag == TAG_BYTE:
            return self._i8()
        if tag == TAG_SHORT:
            return self._i16()
        if tag == TAG_INT:
            return self._i32()
        if tag == TAG_LONG:
            return self._i64()
        if tag == TAG_FLOAT:
            return self._f32()
        if tag == TAG_DOUBLE:
            return self._f64()
        if tag == TAG_BYTE_ARRAY:
            n = self._array_len()
            s = self._take(n)
            return bytes(self.b[s:s + n])
        if tag == TAG_STRING:
            return self._str()
        if tag == TAG_LIST:
            etype = self._u8()
            n = self._array_len()
            if etype == TAG_END:
                return []
            return [self.payload(etype, depth + 1) for _ in range(n)]
        if tag == TAG_COMPOUND:
            return self.named(depth + 1)
        if tag == TAG_INT_ARRAY:
            n = self._array_len()
            s = self._take(4 * n)
            a = array("i")
            a.frombytes(self.b[s:s + 4 * n])
            _to_big_endian(a)
            return a
        if tag == TAG_LONG_ARRAY:
            n = self._array_len()
            s = self._take(8 * n)
            a = array("q")
            a.frombytes(self.b[s:s + 8 * n])
            _to_big_endian(a)
            return a
        raise NbtError("未知标签类型：%d" % tag)

    def named(self, depth: int = 0) -> dict:
        """读取 Compound 的键值对，直到 TAG_End。"""
        if depth > MAX_DEPTH:
            raise NbtError("递归深度超过上限：%d" % MAX_DEPTH)
        out: dict = {}
        while True:
            tag = self._u8()
            if tag == TAG_END:
                return out
            key = self._str()
            out[key] = self.payload(tag, depth)


def _to_big_endian(arr) -> None:
    """``array.frombytes`` 按本机字节序解释，NBT 是大端 → 小端机器需翻转。

    不做这一步，LongArray（``BlockStates`` / 高度图）在 x86 上会整体错位，
    解出来的方块索引全部对不上。
    """
    import sys
    if sys.byteorder == "little":
        arr.byteswap()


def _f32(raw: bytes) -> float:
    import struct
    return struct.unpack(">f", raw)[0]


def _f64(raw: bytes) -> float:
    import struct
    return struct.unpack(">d", raw)[0]


def load_bytes(data: bytes) -> dict:
    """解析一段 NBT（自动识别 gzip/zlib），返回根 Compound。

    多数 MC 文件根标签名为空或 ``Schematic`` / ``Level``；这里统一返回
    **根 Compound 的键值**，调用方直接取字段即可。
    """
    raw = inflate(data)
    r = _Reader(raw)
    tag = r._u8()
    if tag != TAG_COMPOUND:
        raise NbtError("根标签不是 Compound（type=%d）" % tag)
    r._str()  # 根标签名（Schematic / Level / 空）
    return r.named(0)


def load_file(path: str) -> dict:
    """读取一个 NBT 文件（.litematic / .nbt / level.dat）。"""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise NbtError("读取失败：%s" % e) from e
    return load_bytes(data)


def unpack_long_array(values, bits: int, count: int, *,
                      crossing: bool = False, out=None) -> list[int]:
    """把 long 数组拆成 ``count`` 个 ``bits`` 位无符号整数。

    两种打包规则（Minecraft 1.16 是分水岭）：

    - ``crossing=False``（1.16+）：每个 long 内放 ``64 // bits`` 个值，
      剩余高位补零，值不跨 long 边界；
    - ``crossing=True``（1.15-）：值在 long 之间连续排列。

    ``out`` 可传入自定义容器（如 ``array('I')``）以省内存；默认返回 list。
    超出 ``MAX_ARRAY`` 的请求直接拒绝，避免恶意文件撑爆内存。
    """
    if bits < 1 or bits > 64:
        raise NbtError("位宽非法：%d" % bits)
    if count < 0 or count > MAX_ARRAY:
        raise NbtError("元素数量超出上限：%d" % count)
    mask = (1 << bits) - 1
    if out is None:
        out = []
    append = out.append
    if not crossing:
        per = 64 // bits
        for v in values:
            v &= _MASK64
            for _ in range(per):
                if len(out) >= count:
                    return out
                append(v & mask)
                v >>= bits
        return out
    acc = 0
    accbits = 0
    for v in values:
        acc |= (v & _MASK64) << accbits
        accbits += 64
        while accbits >= bits and len(out) < count:
            append(acc & mask)
            acc >>= bits
            accbits -= bits
        if len(out) >= count:
            break
    return out
