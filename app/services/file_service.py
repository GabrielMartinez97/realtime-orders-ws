"""Servicio de validación y almacenamiento seguro de archivos (Fase 5).

Implementa defensa en profundidad para subida de archivos:
1. Límite estricto de lectura en streaming de 2 MB (previene DoS por agotamiento de memoria).
2. Lista blanca (Whitelist) de extensiones seguras (bloquea .svg, .html, .exe, .py, etc.).
3. Inspección de firma binaria real (Magic Bytes / cabecera hexadecimal) y coherencia con la extensión.
4. Nombres aleatorios UUIDv4 y verificación de ruta canónica (previene Path Traversal).
"""

import re
import uuid
from pathlib import Path
from fastapi import HTTPException, UploadFile, status

BASE_DIR = Path(__file__).resolve().parent.parent.parent
UPLOADS_ROOT = (BASE_DIR / "uploads").resolve()
PRODUCTS_UPLOAD_DIR = (UPLOADS_ROOT / "products").resolve()
RECEIPTS_UPLOAD_DIR = (UPLOADS_ROOT / "receipts").resolve()

# Límite máximo estricto: 2 MB (2,097,152 bytes)
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024

ALLOWED_PRODUCT_IMAGE_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}

ALLOWED_RECEIPT_EXTENSIONS: dict[str, str] = {
    **ALLOWED_PRODUCT_IMAGE_EXTENSIONS,
    ".pdf": "application/pdf",
}

SAFE_FILENAME_PATTERN = re.compile(r"^[a-f0-9]{32}\.(png|jpg|jpeg|webp|pdf)$")


def detect_mime_from_magic_bytes(header: bytes) -> str | None:
    """Inspecciona los primeros bytes crudos (Magic Bytes) para identificar el formato real del archivo."""
    if len(header) < 8:
        return None

    # PNG: 89 50 4E 47 0D 0A 1A 0A
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    # JPEG: FF D8 FF
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    # WEBP: "RIFF" + 4 bytes de tamaño + "WEBP"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"

    # PDF: "%PDF-" (25 50 44 46 2D)
    if header.startswith(b"%PDF-"):
        return "application/pdf"

    return None


async def validate_and_save_upload(
    upload: UploadFile,
    *,
    target_dir: Path,
    allowed_extensions: dict[str, str],
) -> tuple[str, str]:
    """Valida extensión, tamaño <= 2 MB y magic bytes reales antes de guardar con nombre UUID aleatorio.

    Retorna (generated_filename, detected_mime_type).
    """
    original_name = (upload.filename or "").strip()
    if not original_name or "." not in original_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo debe tener un nombre y una extensión válida.",
        )

    ext = Path(original_name).suffix.lower()
    expected_mime = allowed_extensions.get(ext)
    if expected_mime is None:
        allowed_list = ", ".join(sorted(allowed_extensions.keys()))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Extensión '{ext}' no permitida. Extensiones válidas: {allowed_list}.",
        )

    # Leemos como máximo MAX_FILE_SIZE_BYTES + 1 para detectar exceso sin agotar la RAM
    content = await upload.read(MAX_FILE_SIZE_BYTES + 1)
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo subido está vacío.",
        )

    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="El archivo excede el tamaño máximo permitido de 2 MB.",
        )

    # Verificación de firma binaria real (Magic Bytes)
    detected_mime = detect_mime_from_magic_bytes(content[:16])
    if detected_mime is None or detected_mime != expected_mime:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Firma binaria (magic bytes) inválida o no coincide con la extensión declarada. "
                "No se permiten archivos renombrados o falsificados."
            ),
        )

    # Generamos nombre aleatorio UUIDv4 y normalizamos .jpeg -> .jpg si aplica
    canonical_ext = ".jpg" if ext == ".jpeg" else ext
    random_filename = f"{uuid.uuid4().hex}{canonical_ext}"

    target_dir.mkdir(parents=True, exist_ok=True)
    destination = (target_dir / random_filename).resolve()

    # Defensa contra Path Traversal: aseguramos que destination sea hijo directo de target_dir
    if destination.parent != target_dir.resolve():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ruta de destino inválida.",
        )

    destination.write_bytes(content)
    return random_filename, detected_mime


def resolve_safe_file_path(base_dir: Path, filename: str) -> tuple[Path, str]:
    """Resuelve de forma segura un archivo dentro de base_dir previniendo Path Traversal."""
    if not SAFE_FILENAME_PATTERN.match(filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nombre de archivo inválido.",
        )

    resolved_base = base_dir.resolve()
    candidate = (resolved_base / filename).resolve()
    if candidate.parent != resolved_base or not candidate.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado.",
        )

    ext = candidate.suffix.lower()
    mime_type = ALLOWED_RECEIPT_EXTENSIONS.get(ext, "application/octet-stream")
    return candidate, mime_type
