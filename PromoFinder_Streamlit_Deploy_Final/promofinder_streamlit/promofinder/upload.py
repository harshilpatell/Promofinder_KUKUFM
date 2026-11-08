"""Safety checks for uploaded screenplay ZIPs (run BEFORE parsing).

The parser never extracts archives to disk: members are read into memory by name.
These checks additionally reject archives that are too large, contain too many files,
unexpected file types, unsafe paths (zip-slip), symlinks, encryption or suspicious
compression ratios (zip bombs).
"""
from __future__ import annotations

import io
import os
import stat
import zipfile
from dataclasses import dataclass, field

LIMITS = {
    "max_zip_bytes": int(os.getenv("PROMOFINDER_MAX_ZIP_MB", "20")) * 1024 * 1024,
    "max_entries": 400,
    "max_txt_files": 300,
    "max_file_bytes": 2 * 1024 * 1024,
    "max_total_uncompressed": 60 * 1024 * 1024,
    "max_ratio": 100,
}
IGNORED = ("__MACOSX/", ".DS_Store", "Thumbs.db", "desktop.ini")


class ZipValidationError(ValueError):
    """Raised with a user-readable message when an upload is rejected."""


@dataclass
class ZipCheck:
    ok: bool
    txt_files: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


def _unsafe_path(name: str) -> bool:
    n = name.replace("\\", "/")
    if n.startswith("/") or (len(n) > 1 and n[1] == ":"):
        return True
    return any(part == ".." for part in n.split("/"))


def check_zip(data: bytes, limits: dict | None = None) -> ZipCheck:
    L = {**LIMITS, **(limits or {})}
    res = ZipCheck(ok=False)
    if not data:
        res.errors.append("The upload is empty.")
        return res
    if len(data) > L["max_zip_bytes"]:
        res.errors.append(f"ZIP is {len(data)/1e6:.1f} MB; the limit is {L['max_zip_bytes']/1e6:.0f} MB.")
        return res
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except zipfile.BadZipFile:
        res.errors.append("This file is not a valid ZIP archive.")
        return res
    if len(infos) > L["max_entries"]:
        res.errors.append(f"ZIP has {len(infos)} entries; the limit is {L['max_entries']}.")
        return res
    total = 0
    for i in infos:
        name = i.filename
        if _unsafe_path(name):
            res.errors.append(f"Unsafe path in archive (possible zip-slip): '{name}'.")
            continue
        if i.flag_bits & 0x1:
            res.errors.append(f"Encrypted file not supported: '{name}'.")
            continue
        if stat.S_ISLNK(i.external_attr >> 16):
            res.errors.append(f"Symbolic link not allowed: '{name}'.")
            continue
        if i.is_dir():
            continue
        base = name.split("/")[-1]
        if any(name.startswith(x) or base == x or f"/{x}" in name for x in IGNORED) or base.startswith("._"):
            res.warnings.append(f"Ignored system file '{name}'.")
            continue
        if not base.lower().endswith(".txt"):
            res.errors.append(f"Unexpected file type '{name}' (only .txt screenplay files are accepted).")
            continue
        if i.file_size > L["max_file_bytes"]:
            res.errors.append(f"'{name}' is {i.file_size/1e6:.1f} MB uncompressed; limit {L['max_file_bytes']/1e6:.0f} MB per file.")
            continue
        if i.compress_size and i.file_size / max(i.compress_size, 1) > L["max_ratio"]:
            res.errors.append(f"'{name}' has a suspicious compression ratio (possible zip bomb).")
            continue
        total += i.file_size
        res.txt_files.append(name)
    if total > L["max_total_uncompressed"]:
        res.errors.append(f"Total uncompressed size {total/1e6:.1f} MB exceeds {L['max_total_uncompressed']/1e6:.0f} MB.")
    if len(res.txt_files) > L["max_txt_files"]:
        res.errors.append(f"{len(res.txt_files)} .txt files; the limit is {L['max_txt_files']} episodes per upload.")
    if not res.txt_files and not res.errors:
        res.errors.append("No .txt screenplay files found in the ZIP.")
    res.ok = not res.errors
    return res


def require_valid_zip(data: bytes, limits: dict | None = None) -> ZipCheck:
    chk = check_zip(data, limits)
    if not chk.ok:
        raise ZipValidationError(" ".join(chk.errors[:5]) + (" …" if len(chk.errors) > 5 else ""))
    return chk
