"""证件照片本地存储。文件名由系统生成，避免路径穿越。"""
import secrets
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import PHOTOS_DIR

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 8 * 1024 * 1024


def save_id_photo(upload: UploadFile, kind: str) -> str:
    ext = Path(upload.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 jpg/png/webp 图片")
    data = upload.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片不能超过 8MB")
    name = f"{kind}_{secrets.token_hex(8)}{ext}"
    target = PHOTOS_DIR / name
    # 二次防护：解析后的绝对路径必须位于 PHOTOS_DIR 内
    if PHOTOS_DIR.resolve() not in target.resolve().parents:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "非法存储路径")
    target.write_bytes(data)
    return name


def resolve_photo_path(stored_name: str) -> Path:
    p = (PHOTOS_DIR / stored_name).resolve()
    if PHOTOS_DIR.resolve() not in p.parents or not p.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    return p
