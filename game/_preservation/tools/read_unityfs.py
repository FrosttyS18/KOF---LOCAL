"""Read original UnityFS data blocks without modifying the cache or installing packages."""
import pathlib
import struct


def decode(data, size, mode):
    if size > 256 * 1024 * 1024:
        raise ValueError("UnityFS block exceeds analysis limit")
    if mode == 0:
        if len(data) != size:
            raise ValueError("Invalid uncompressed block size")
        return data
    if mode not in (2, 3):
        raise ValueError(f"Unsupported compression mode {mode}")
    output = bytearray()
    offset = 0
    while offset < len(data):
        token = data[offset]
        offset += 1
        length = token >> 4
        if length == 15:
            while True:
                extension = data[offset]
                offset += 1
                length += extension
                if extension != 255:
                    break
        output.extend(data[offset:offset + length])
        offset += length
        if offset == len(data):
            break
        distance = int.from_bytes(data[offset:offset + 2], "little")
        offset += 2
        length = (token & 15) + 4
        if token & 15 == 15:
            while True:
                extension = data[offset]
                offset += 1
                length += extension
                if extension != 255:
                    break
        if not 0 < distance <= len(output) or len(output) + length > size:
            raise ValueError("Invalid LZ4 back reference")
        for _ in range(length):
            output.append(output[-distance])
    if len(output) != size:
        raise ValueError("Invalid decompressed size")
    return bytes(output)


def load(path):
    data = pathlib.Path(path).read_bytes()
    if not data.startswith(b"UnityFS\0"):
        raise ValueError("Not a UnityFS file")
    version = struct.unpack_from(">I", data, 8)[0]
    offset = 12
    for _ in range(2):
        offset = data.index(b"\0", offset) + 1
    total, compressed, uncompressed, flags = struct.unpack_from(">QIII", data, offset)
    offset += 20
    if total != len(data):
        raise ValueError("Unexpected UnityFS file size")
    if version >= 7:
        offset = (offset + 15) // 16 * 16
    metadata = data[-compressed:] if flags & 128 else data[offset:offset + compressed]
    metadata = decode(metadata, uncompressed, flags & 63)
    start = offset if flags & 128 else offset + compressed
    if flags & 512:
        start = (start + 15) // 16 * 16
    count = struct.unpack_from(">I", metadata, 16)[0]
    if count > 10000:
        raise ValueError("Too many UnityFS blocks")
    output = bytearray()
    for number in range(count):
        size, packed, block_flags = struct.unpack_from(">IIH", metadata, 20 + number * 10)
        output.extend(decode(data[start:start + packed], size, block_flags & 63))
        start += packed
        if len(output) > 256 * 1024 * 1024:
            raise ValueError("Bundle exceeds analysis limit")
    return bytes(output)
