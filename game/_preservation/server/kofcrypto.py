"""Ciphers used by the KOF ALLSTAR client (AES-128-CBC, PKCS7)."""
import base64, gzip
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# boot config: SecureKey.GetKeyHexString("neo4567neo123456" / "neo4567890neo456") -> ASCII bytes
CONFIG_KEY = (b"neo4567neo123456", b"neo4567890neo456")
# NetworkRequest.GetCipher fallback (session/pcAuth): NetmarbleS.Cipher(type, key, iv)
PCAUTH_KEY = (bytes.fromhex("CA4BB353B60D4F10321ED79DB1B7A2F1"), bytes.fromhex("CD2F0231A8D43378FF29C26D95E3B6AB"))


def encrypt(plain: bytes, key) -> bytes:
    return AES.new(key[0], AES.MODE_CBC, key[1]).encrypt(pad(plain, 16))


def decrypt(data: bytes, key) -> bytes:
    return unpad(AES.new(key[0], AES.MODE_CBC, key[1]).decrypt(data), 16)


def encrypt_b64(plain: bytes, key) -> bytes:
    return base64.b64encode(encrypt(plain, key))


def try_decode(body: bytes, keys) -> tuple:
    """Best-effort decode of a request body: returns (description, plaintext bytes)."""
    if not body:
        return "empty", b""
    steps = []
    data = body
    try:
        raw = base64.b64decode(data, validate=True)
        steps.append("b64")
        data = raw
    except Exception:
        pass
    if len(data) % 16 == 0 and steps:
        for name, key in keys.items():
            try:
                data = decrypt(data, key)
                steps.append("aes:" + name)
                break
            except Exception:
                continue
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
        steps.append("gzip")
    return "+".join(steps) or "plain", data
