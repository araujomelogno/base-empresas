"""Archivos subidos (bases, .sav): Cloud Storage en producción, carpeta local en desarrollo."""
import hashlib
import pathlib
import uuid

from fastapi import HTTPException

from . import settings

TIPOS = {".xlsx": "xlsx", ".xls": "xlsx", ".csv": "csv", ".txt": "csv", ".sav": "sav"}
MAX_BYTES = 200 * 1024 * 1024


def tipo_de(nombre: str) -> str:
    ext = pathlib.Path(nombre).suffix.lower()
    if ext not in TIPOS:
        raise HTTPException(415, f"Formato no soportado: {ext or 'sin extensión'} (se aceptan .xlsx, .csv y .sav)")
    return TIPOS[ext]


def _bucket():
    from google.cloud import storage

    return storage.Client().bucket(settings.STORAGE_BUCKET)


def guardar(conn, nombre: str, datos: bytes, actor: str) -> dict:
    if len(datos) > MAX_BYTES:
        raise HTTPException(413, "Archivo demasiado grande (máximo 200 MB)")
    tipo = tipo_de(nombre)
    sha = hashlib.sha256(datos).hexdigest()
    ruta = f"subidas/{sha[:2]}/{uuid.uuid4().hex}{pathlib.Path(nombre).suffix.lower()}"
    if settings.STORAGE_BUCKET:
        _bucket().blob(ruta).upload_from_string(datos)
    else:
        p = pathlib.Path(settings.STORAGE_DIR) / ruta
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(datos)
    return conn.execute(
        "INSERT INTO archivo (nombre, tipo, sha256, ruta, tamano, subido_por) VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (nombre, tipo, sha, ruta, len(datos), actor),
    ).fetchone()


def leer(archivo: dict) -> bytes:
    if settings.STORAGE_BUCKET:
        return _bucket().blob(archivo["ruta"]).download_as_bytes()
    return (pathlib.Path(settings.STORAGE_DIR) / archivo["ruta"]).read_bytes()
