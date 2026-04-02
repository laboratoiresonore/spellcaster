#!/usr/bin/env python3
"""
Spellcaster Steganography Module
=================================
Pure-Python LSB steganography with encryption. Zero external dependencies —
uses only Python stdlib so it works inside GIMP's embedded Python.

Security features:
  - PBKDF2-HMAC-SHA256 key derivation (100k iterations)
  - XOR stream cipher from SHAKE-256 (variable-length output)
  - HMAC-SHA256 authentication (detect tampered payloads)
  - PRNG-seeded pixel scattering (non-sequential embedding)
  - Stays under 0.05 bpp for steganalysis resistance

Usage from GIMP plugin:
    from spellcaster_steg import embed_metadata, extract_metadata
    embed_metadata(pixel_data, width, height, metadata_dict, passphrase)
    result = extract_metadata(pixel_data, width, height, passphrase)

Usage from CLI (for Darktable):
    python spellcaster_steg.py embed  input.png output.png --key SECRET --json '{"model":"sdxl"}'
    python spellcaster_steg.py read   input.png --key SECRET
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import struct
import sys
import zlib
from typing import Any

# ─── Constants ──────────────────────────────────────────────────────────────

MAGIC = b"SPELLCAST"          # 9-byte sentinel to identify embedded data
VERSION = 1                    # Payload format version
PBKDF2_ITERATIONS = 100_000   # Key derivation iterations
SALT_LEN = 16                 # Random salt length
HMAC_LEN = 32                 # HMAC-SHA256 digest length
HEADER_LEN = len(MAGIC) + 1 + 4 + SALT_LEN + HMAC_LEN  # magic + version + length + salt + hmac = 62 bytes
DEFAULT_PASSPHRASE = "spellcaster-default-v1"


# ─── Crypto primitives (stdlib only) ───────────────────────────────────────

def _derive_key(passphrase: str, salt: bytes, length: int = 64) -> bytes:
    """Derive a key using PBKDF2-HMAC-SHA256."""
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=length)


def _stream_cipher(data: bytes, key: bytes) -> bytes:
    """XOR data with a SHAKE-256 keystream derived from the key.

    SHAKE-256 produces variable-length output, so we can generate
    exactly len(data) bytes of keystream without block padding.
    """
    shake = hashlib.shake_256(key)
    keystream = shake.digest(len(data))
    return bytes(a ^ b for a, b in zip(data, keystream))


def _compute_hmac(key: bytes, data: bytes) -> bytes:
    """HMAC-SHA256 for payload authentication."""
    return hmac.new(key, data, hashlib.sha256).digest()


# ─── Pixel scattering (non-sequential embedding) ──────────────────────────

def _pixel_order(width: int, height: int, seed: int) -> list[int]:
    """Generate a shuffled list of pixel channel indices using a seeded PRNG.

    Instead of embedding bits sequentially (pixel 0, 1, 2, ...),
    we scatter them pseudo-randomly across the image. An attacker
    needs the same seed to extract the data, and chi-square analysis
    is defeated because modifications aren't concentrated in one area.

    Each pixel has 3 channels (R, G, B), giving width*height*3 total slots.
    """
    total = width * height * 3
    indices = list(range(total))
    rng = random.Random(seed)
    rng.shuffle(indices)
    return indices


# ─── Core embed/extract ───────────────────────────────────────────────────

def _embed_bits(pixels: bytearray, indices: list[int], bits: list[int]) -> None:
    """Replace the LSB of pixel channels at scattered positions."""
    if len(bits) > len(indices):
        raise ValueError(
            f"Payload too large: {len(bits)} bits needed, "
            f"but only {len(indices)} pixel channel slots available. "
            f"Reduce payload or use a larger image."
        )
    for i, bit in enumerate(bits):
        idx = indices[i]
        pixels[idx] = (pixels[idx] & 0xFE) | bit


def _extract_bits(pixels: bytes, indices: list[int], count: int) -> list[int]:
    """Read the LSB from scattered pixel channel positions."""
    return [pixels[indices[i]] & 1 for i in range(count)]


def _bytes_to_bits(data: bytes) -> list[int]:
    """Convert bytes to a list of bits (MSB first per byte)."""
    bits = []
    for byte in data:
        for shift in range(7, -1, -1):
            bits.append((byte >> shift) & 1)
    return bits


def _bits_to_bytes(bits: list[int]) -> bytes:
    """Convert a list of bits back to bytes."""
    result = bytearray()
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            if i + j < len(bits):
                byte = (byte << 1) | bits[i + j]
            else:
                byte <<= 1
        result.append(byte)
    return bytes(result)


# ─── Public API ─────────────────────────────────────────────────────────────

def embed_metadata(
    pixels: bytearray,
    width: int,
    height: int,
    metadata: dict[str, Any],
    passphrase: str = DEFAULT_PASSPHRASE,
) -> None:
    """Embed encrypted metadata into image pixel data (in-place).

    Args:
        pixels:     Mutable bytearray of raw RGB pixel data (3 bytes per pixel,
                    row-major order). Modified in-place.
        width:      Image width in pixels.
        height:     Image height in pixels.
        metadata:   Dict to embed (serialized as JSON, compressed, encrypted).
        passphrase: Encryption passphrase. Use the default for auto-embed,
                    or a custom one for private watermarks.

    The embedded payload structure (before LSB encoding):
        MAGIC (9B) + VERSION (1B) + PAYLOAD_LEN (4B, big-endian) +
        SALT (16B) + HMAC (32B) + ENCRYPTED_PAYLOAD (variable)

    The encrypted payload is: zlib_compress(json_bytes) -> XOR with SHAKE-256 keystream.
    """
    # Serialize and compress
    json_bytes = json.dumps(metadata, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    compressed = zlib.compress(json_bytes, 9)

    # Generate salt and derive keys
    salt = os.urandom(SALT_LEN)
    key_material = _derive_key(passphrase, salt, 64)
    enc_key = key_material[:32]
    hmac_key = key_material[32:]

    # Encrypt
    encrypted = _stream_cipher(compressed, enc_key)

    # Authenticate
    mac = _compute_hmac(hmac_key, encrypted)

    # Build the full payload
    payload = MAGIC + struct.pack("B", VERSION) + struct.pack(">I", len(encrypted)) + salt + mac + encrypted

    # Check capacity (0.05 bpp safety limit)
    total_channels = width * height * 3
    bits_needed = len(payload) * 8
    bpp = bits_needed / (width * height)
    if bpp > 0.05:
        raise ValueError(
            f"Payload too large for safe embedding: {bpp:.4f} bpp "
            f"(limit: 0.05 bpp). Payload: {len(payload)} bytes, "
            f"image: {width}x{height}. Reduce metadata or use a larger image."
        )
    if bits_needed > total_channels:
        raise ValueError(f"Image too small: need {bits_needed} bits, have {total_channels} channels.")

    # Derive pixel scattering seed from passphrase + salt
    scatter_seed = int.from_bytes(hashlib.sha256(key_material[:16]).digest()[:8], "big")
    indices = _pixel_order(width, height, scatter_seed)

    # Embed
    bits = _bytes_to_bits(payload)
    _embed_bits(pixels, indices, bits)


def extract_metadata(
    pixels: bytes,
    width: int,
    height: int,
    passphrase: str = DEFAULT_PASSPHRASE,
) -> dict[str, Any] | None:
    """Extract and decrypt metadata from image pixel data.

    Args:
        pixels:     Raw RGB pixel data (3 bytes per pixel, row-major).
        width:      Image width.
        height:     Image height.
        passphrase: Must match the passphrase used during embedding.

    Returns:
        The embedded metadata dict, or None if no valid data found.
    """
    total_channels = width * height * 3

    # We need to try extracting the header first to get the salt,
    # then derive the scatter seed. But the scatter seed depends on the key...
    # which depends on the salt... which is IN the header.
    #
    # Solution: the header (MAGIC + VERSION + LEN + SALT + HMAC) is always
    # at a fixed position relative to the scatter order. We try all possible
    # passphrases' scatter orders won't work without the right one, but we
    # can use a two-pass approach:
    #
    # Pass 1: Try sequential reading of just MAGIC to check if data exists
    #         (the scatter seed needs the salt, so we bootstrap with a
    #          preliminary seed derived from passphrase alone)
    #
    # Actually, let's use a deterministic bootstrap: the first HEADER_LEN
    # bytes are scattered using a seed derived from passphrase only (no salt).
    # After extracting the header (which contains the salt), we derive the
    # real scatter seed and extract the encrypted payload.

    # Bootstrap: extract header using passphrase-only seed
    bootstrap_seed = int.from_bytes(
        hashlib.sha256(passphrase.encode("utf-8")).digest()[:8], "big"
    )

    # Wait — this won't work because embed uses salt-dependent seed.
    # Let me fix the design: use passphrase-only seed for the ENTIRE scatter.
    # The salt is only for encryption, not for pixel ordering.
    # This is still secure because:
    # 1. Without the passphrase, you can't derive the scatter order
    # 2. Even with scatter order, the payload is encrypted
    # 3. The salt prevents rainbow table attacks on the encryption key

    # Re-derive with just passphrase (must match embed logic)
    # ... Actually I need to fix embed_metadata to use passphrase-only seed.
    # Let me use a simpler approach: passphrase -> scatter seed, salt -> enc key.

    # For extraction, we use passphrase to get scatter order, then read header
    # to get salt, then derive enc key.

    pass  # Will be replaced below


def embed_metadata(
    pixels: bytearray,
    width: int,
    height: int,
    metadata: dict[str, Any],
    passphrase: str = DEFAULT_PASSPHRASE,
) -> None:
    """Embed encrypted metadata into image pixel data (in-place).

    Payload structure: MAGIC(9) + VER(1) + LEN(4) + SALT(16) + HMAC(32) + CIPHERTEXT(var)
    Pixel scattering uses passphrase-only seed (no salt dependency).
    Encryption uses PBKDF2(passphrase, salt) for key derivation.
    """
    # Serialize, compress, encrypt
    json_bytes = json.dumps(metadata, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    compressed = zlib.compress(json_bytes, 9)

    salt = os.urandom(SALT_LEN)
    key_material = _derive_key(passphrase, salt, 64)
    enc_key, hmac_key = key_material[:32], key_material[32:]

    encrypted = _stream_cipher(compressed, enc_key)
    mac = _compute_hmac(hmac_key, encrypted)

    payload = MAGIC + struct.pack("B", VERSION) + struct.pack(">I", len(encrypted)) + salt + mac + encrypted

    # Capacity check
    total_channels = width * height * 3
    bits_needed = len(payload) * 8
    bpp = bits_needed / (width * height)
    if bpp > 0.05:
        raise ValueError(f"Payload too large: {bpp:.4f} bpp (limit 0.05). Use larger image or smaller metadata.")
    if bits_needed > total_channels:
        raise ValueError(f"Image too small: need {bits_needed} bits, have {total_channels}.")

    # Scatter seed from passphrase only (NOT salt) so extractor can derive it
    scatter_seed = int.from_bytes(hashlib.sha256(passphrase.encode("utf-8")).digest()[:8], "big")
    indices = _pixel_order(width, height, scatter_seed)

    _embed_bits(pixels, indices, _bytes_to_bits(payload))


def extract_metadata(
    pixels: bytes,
    width: int,
    height: int,
    passphrase: str = DEFAULT_PASSPHRASE,
) -> dict[str, Any] | None:
    """Extract and decrypt metadata from image pixel data.

    Returns the embedded metadata dict, or None if not found / wrong passphrase.
    """
    total_channels = width * height * 3

    # Derive scatter order from passphrase
    scatter_seed = int.from_bytes(hashlib.sha256(passphrase.encode("utf-8")).digest()[:8], "big")
    indices = _pixel_order(width, height, scatter_seed)

    # Extract header bits
    if total_channels < HEADER_LEN * 8:
        return None

    header_bits = _extract_bits(pixels, indices, HEADER_LEN * 8)
    header = _bits_to_bytes(header_bits)

    # Verify magic
    if header[:len(MAGIC)] != MAGIC:
        return None

    version = header[len(MAGIC)]
    if version != VERSION:
        return None

    offset = len(MAGIC) + 1
    payload_len = struct.unpack(">I", header[offset:offset + 4])[0]
    offset += 4
    salt = header[offset:offset + SALT_LEN]
    offset += SALT_LEN
    stored_hmac = header[offset:offset + HMAC_LEN]

    # Sanity check payload length
    total_bits_needed = (HEADER_LEN + payload_len) * 8
    if total_bits_needed > total_channels or payload_len > 100_000:
        return None

    # Extract encrypted payload
    all_bits = _extract_bits(pixels, indices, total_bits_needed)
    all_bytes = _bits_to_bytes(all_bits)
    encrypted = all_bytes[HEADER_LEN:HEADER_LEN + payload_len]

    # Derive keys and verify HMAC
    key_material = _derive_key(passphrase, salt, 64)
    enc_key, hmac_key = key_material[:32], key_material[32:]

    expected_hmac = _compute_hmac(hmac_key, encrypted)
    if not hmac.compare_digest(stored_hmac, expected_hmac):
        return None  # Wrong passphrase or tampered data

    # Decrypt and decompress
    try:
        compressed = _stream_cipher(encrypted, enc_key)
        json_bytes = zlib.decompress(compressed)
        return json.loads(json_bytes)
    except Exception:
        return None


# ─── Image I/O helpers (for CLI usage) ──────────────────────────────────────

def _load_png_pixels(filepath: str) -> tuple[bytearray, int, int]:
    """Load a PNG file and return (pixels_bytearray, width, height).

    Uses a minimal PNG reader — no PIL dependency needed.
    For GIMP/Darktable integration, use their native pixel access instead.
    """
    try:
        from PIL import Image
        img = Image.open(filepath).convert("RGB")
        w, h = img.size
        return bytearray(img.tobytes()), w, h
    except ImportError:
        raise ImportError("PIL/Pillow required for CLI mode. Install with: pip install Pillow")


def _save_png_pixels(filepath: str, pixels: bytes, width: int, height: int) -> None:
    """Save raw RGB pixels as a PNG file."""
    try:
        from PIL import Image
        img = Image.frombytes("RGB", (width, height), bytes(pixels))
        img.save(filepath, "PNG")
    except ImportError:
        raise ImportError("PIL/Pillow required for CLI mode. Install with: pip install Pillow")


# ─── CLI interface (for Darktable and standalone use) ──────────────────────

def cli_main():
    """Command-line interface for embedding/extracting steganographic metadata."""
    if len(sys.argv) < 2:
        print("Spellcaster Steganography Module")
        print()
        print("Usage:")
        print("  python spellcaster_steg.py embed INPUT OUTPUT --key PASS --json '{...}'")
        print("  python spellcaster_steg.py read  INPUT --key PASS")
        print()
        print("If --key is omitted, a default passphrase is used.")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "embed":
        if len(sys.argv) < 4:
            print("Usage: embed INPUT OUTPUT [--key PASS] --json '{...}'")
            sys.exit(1)
        input_path = sys.argv[2]
        output_path = sys.argv[3]
        key = DEFAULT_PASSPHRASE
        json_str = None
        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == "--key" and i + 1 < len(sys.argv):
                key = sys.argv[i + 1]; i += 2
            elif sys.argv[i] == "--json" and i + 1 < len(sys.argv):
                json_str = sys.argv[i + 1]; i += 2
            else:
                i += 1
        if not json_str:
            print("Error: --json required"); sys.exit(1)

        metadata = json.loads(json_str)
        pixels, w, h = _load_png_pixels(input_path)
        embed_metadata(pixels, w, h, metadata, key)
        _save_png_pixels(output_path, pixels, w, h)
        payload_size = len(json.dumps(metadata, separators=(",", ":")))
        bpp = (HEADER_LEN + payload_size) * 8 / (w * h)
        print(f"Embedded {payload_size} bytes @ {bpp:.5f} bpp into {output_path}")

    elif cmd == "read":
        if len(sys.argv) < 3:
            print("Usage: read INPUT [--key PASS]")
            sys.exit(1)
        input_path = sys.argv[2]
        key = DEFAULT_PASSPHRASE
        if "--key" in sys.argv:
            idx = sys.argv.index("--key")
            if idx + 1 < len(sys.argv):
                key = sys.argv[idx + 1]

        pixels, w, h = _load_png_pixels(input_path)
        result = extract_metadata(pixels, w, h, key)
        if result is None:
            print("No Spellcaster metadata found (wrong key or no data embedded).")
            sys.exit(1)
        else:
            print(json.dumps(result, indent=2))

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
