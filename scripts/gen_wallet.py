"""
生成一个 EVM 收款钱包（纯标准库，不依赖 web3/eth-account）。

用途：x402 付费端点需要一个 payTo 地址才能工作。本机没有加密库、也装不了包，
所以这里用 secp256k1 + Keccak-256 自己算，逻辑与以太坊地址派生规则完全一致。

安全说明：
- 私钥只在本地生成、只写到 D 盘的独立目录，绝不进 git 仓库、绝不打印到日志。
- 生成后请立刻备份私钥文件；私钥丢失 = 钱包里的钱永久取不出来。

用法：
    python gen_wallet.py            # 生成新钱包，写到 ../.wallet/wallet.json
    python gen_wallet.py --selftest # 只跑已知向量自检，不生成钱包
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Keccak-256（以太坊用的是原始 Keccak，填充字节 0x01，不是 NIST SHA3 的 0x06）
# ---------------------------------------------------------------------------

_ROUND_CONSTANTS = [
    0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000,
    0x000000000000808B, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
    0x000000000000008A, 0x0000000000000088, 0x0000000080008009, 0x000000008000000A,
    0x000000008000808B, 0x800000000000008B, 0x8000000000008089, 0x8000000000008003,
    0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
    0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008,
]

_ROTATIONS = [
    [0, 36, 3, 41, 18],
    [1, 44, 10, 45, 2],
    [62, 6, 43, 15, 61],
    [28, 55, 25, 21, 56],
    [27, 20, 39, 8, 14],
]

_MASK = (1 << 64) - 1


def _rol(x: int, n: int) -> int:
    n %= 64
    return ((x << n) | (x >> (64 - n))) & _MASK


def _keccak_f(state: list[list[int]]) -> None:
    """对 5x5 的 64 位 lane 矩阵做 24 轮 Keccak 置换"""
    for rnd in range(24):
        # θ
        c = [state[x][0] ^ state[x][1] ^ state[x][2] ^ state[x][3] ^ state[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        for x in range(5):
            for y in range(5):
                state[x][y] ^= d[x]

        # ρ + π
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(state[x][y], _ROTATIONS[x][y])

        # χ
        for x in range(5):
            for y in range(5):
                state[x][y] = b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y])

        # ι
        state[0][0] ^= _ROUND_CONSTANTS[rnd]


def keccak256(data: bytes) -> bytes:
    rate = 136  # 1088 bit
    # 原始 Keccak 填充：0x01 ... 0x80
    padded = bytearray(data)
    padded.append(0x01)
    while len(padded) % rate != 0:
        padded.append(0x00)
    padded[-1] |= 0x80

    state = [[0] * 5 for _ in range(5)]
    for off in range(0, len(padded), rate):
        block = padded[off : off + rate]
        for i in range(rate // 8):
            lane = int.from_bytes(block[i * 8 : i * 8 + 8], "little")
            state[i % 5][i // 5] ^= lane
        _keccak_f(state)

    out = bytearray()
    for i in range(4):
        out += state[i % 5][i // 5].to_bytes(8, "little")
    return bytes(out)


# ---------------------------------------------------------------------------
# secp256k1
# ---------------------------------------------------------------------------

P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F
N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
GX = 0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
GY = 0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8


def _inv(a: int, m: int) -> int:
    return pow(a, m - 2, m)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        lam = 3 * x1 * x1 % P * _inv(2 * y1 % P, P) % P
    else:
        lam = (y2 - y1) * _inv((x2 - x1) % P, P) % P
    x3 = (lam * lam - x1 - x2) % P
    y3 = (lam * (x1 - x3) - y1) % P
    return (x3, y3)


def _mul(k: int, point):
    result = None
    addend = point
    while k:
        if k & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        k >>= 1
    return result


def privkey_to_address(priv_int: int) -> str:
    """私钥 → 0x 开头的 EIP-55 校验和地址"""
    pub = _mul(priv_int, (GX, GY))
    if pub is None:
        raise ValueError("无效私钥")
    raw = pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big")
    addr_hex = keccak256(raw)[-20:].hex()
    # EIP-55 大小写校验
    digest = keccak256(addr_hex.encode()).hex()
    checksum = "".join(
        ch.upper() if ch.isalpha() and int(digest[i], 16) >= 8 else ch
        for i, ch in enumerate(addr_hex)
    )
    return "0x" + checksum


def selftest() -> bool:
    ok = True

    # 已知向量 1：Keccak-256("") 应为 c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470
    got = keccak256(b"").hex()
    want = "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    print(f"[1] keccak256('')      {'OK ' if got == want else 'FAIL'} {got}")
    ok &= got == want

    # 已知向量 2：私钥 1 → 0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf
    got2 = privkey_to_address(1)
    want2 = "0x7E5F4552091A69125d5DfCb7b8C2659029395Bdf"
    print(f"[2] privkey=1 → addr    {'OK ' if got2 == want2 else 'FAIL'} {got2}")
    ok &= got2 == want2

    # 已知向量 3：私钥 2 → 0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF
    got3 = privkey_to_address(2)
    want3 = "0x2B5AD5c4795c026514f8317c7a215E218DcCD6cF"
    print(f"[3] privkey=2 → addr    {'OK ' if got3 == want3 else 'FAIL'} {got3}")
    ok &= got3 == want3

    # 已知向量 4：EIP-55 官方示例地址
    got4 = privkey_to_address(int("0x4646464646464646464646464646464646464646464646464646464646464646", 16))
    want4 = "0x9d8A62f656a8d1615C1294fd71e9CFb3E4855A4F"
    print(f"[4] EIP-55 示例地址     {'OK ' if got4 == want4 else 'FAIL'} {got4}")
    ok &= got4 == want4

    print("自检结果：" + ("全部通过" if ok else "存在失败项"))
    return ok


def main() -> int:
    if "--selftest" in sys.argv:
        return 0 if selftest() else 1

    if not selftest():
        print("自检未通过，拒绝生成钱包，避免得到错误地址。")
        return 1

    out_dir = Path(__file__).resolve().parent.parent / ".wallet"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "wallet.json"
    if out_file.exists():
        print(f"钱包已存在，不覆盖：{out_file}")
        data = json.loads(out_file.read_text(encoding="utf-8"))
        print(f"地址：{data['address']}")
        return 0

    priv = secrets.randbelow(N - 1) + 1
    priv_hex = "0x" + priv.to_bytes(32, "big").hex()
    address = privkey_to_address(priv)

    payload = {
        "address": address,
        "private_key": priv_hex,
        "network_note": "EVM 通用地址（Base / Base Sepolia / Polygon / Ethereum 均可收款）",
        "warning": "私钥泄露即资产被盗；丢失即资产永久无法取回。请立刻离线备份。",
    }
    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(out_file, 0o600)
    except OSError:
        pass

    print(f"✓ 钱包已生成：{out_file}")
    print(f"  地址：{address}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
