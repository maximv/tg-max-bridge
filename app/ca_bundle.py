# ca_bundle.py — CA-бандл с сертификатами НУЦ Минцифры для platform-api2.max.ru
#
# httpx/certifi по умолчанию НЕ видят системный store после update-ca-certificates,
# поэтому явно собираем бандл: certifi (или системный) + russian_trusted_*.crt.

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_BUNDLE_PATH: str | None = None
_CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


def get_verify_path() -> str:
    """Путь к PEM-бандлу для аргумента httpx verify=..."""
    global _BUNDLE_PATH
    if _BUNDLE_PATH and Path(_BUNDLE_PATH).exists():
        return _BUNDLE_PATH

    chunks: list[str] = []

    try:
        import certifi

        chunks.append(Path(certifi.where()).read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        system = Path("/etc/ssl/certs/ca-certificates.crt")
        if system.is_file():
            chunks.append(system.read_text(encoding="utf-8", errors="ignore"))

    for cert in sorted(_CERTS_DIR.glob("russian_trusted_*.crt")):
        text = cert.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n").replace("\r", "\n").strip()
        if text and "BEGIN CERTIFICATE" in text:
            chunks.append(text)

    fd, path = tempfile.mkstemp(prefix="tg-max-ca-", suffix=".pem")
    os.close(fd)
    Path(path).write_text("\n".join(chunks) + "\n", encoding="utf-8")
    _BUNDLE_PATH = path
    return path
