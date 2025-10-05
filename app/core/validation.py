import logging
import os
import re
from typing import Optional

from fastapi import HTTPException, UploadFile


logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


def validate_file(file: UploadFile) -> None:
    if getattr(file, 'size', None) and file.size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    file_ext = os.path.splitext(file.filename.lower())[1]
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid MIME type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}")

    if '..' in file.filename or '/' in file.filename or '\\' in file.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")


def validate_inputs(user_id: Optional[str] = None, memory_id: Optional[str] = None) -> None:
    if user_id and not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        raise HTTPException(status_code=400, detail="Invalid user_id format")

    if memory_id and not re.match(r'^[a-zA-Z0-9_-]+$', memory_id):
        raise HTTPException(status_code=400, detail="Invalid memory_id format")


