import logging
from typing import Optional
from urllib.parse import urlparse

from fastapi import HTTPException
from supabase import create_client, Client

from ..core.config import Config


logger = logging.getLogger(__name__)


def get_client() -> Client:
    return create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)


def _infer_storage_path_from_url(url_or_path: str, bucket: str) -> str:
    if not url_or_path:
        raise HTTPException(status_code=400, detail="Empty figurine URL/path")
    if '://' not in url_or_path:
        return url_or_path.lstrip('/')
    parsed = urlparse(url_or_path)
    segments = [seg for seg in parsed.path.split('/') if seg]
    try:
        bucket_index = segments.index(bucket)
        relative_segments = segments[bucket_index + 1:]
        if not relative_segments:
            raise ValueError("No object path after bucket")
        return '/'.join(relative_segments)
    except ValueError:
        return parsed.path.lstrip('/')


def create_signed_url_for_storage_object(url_or_path: str, *, expires_in_seconds: int = 3600) -> str:
    try:
        supabase = get_client()
        object_path = _infer_storage_path_from_url(url_or_path, Config.SUPABASE_BUCKET)
        signed_result = supabase.storage.from_(Config.SUPABASE_BUCKET).create_signed_url(
            object_path,
            expires_in_seconds
        )

        if isinstance(signed_result, dict):
            signed_url = (
                signed_result.get('signedURL') or
                signed_result.get('signed_url') or
                signed_result.get('signedUrl') or
                signed_result.get('url') or
                str(signed_result)
            )
        else:
            signed_url = str(signed_result)

        if not signed_url or not isinstance(signed_url, str):
            raise RuntimeError("Invalid signed URL response from Supabase")

        return signed_url
    except Exception as e:
        logger.error(f"Failed to create signed URL: {e}")
        raise HTTPException(status_code=500, detail="Failed to create signed URL for image")


def upload_to_supabase(file_bytes: bytes, filename: str, content_type: str, user_id: Optional[str] = None):

    try:
        supabase: Client = get_client()

        if user_id:
            file_path = f"{user_id}/3d-models/{filename}"
        else:
            file_path = f"generated/3d-models/{filename}"

        upload_result = supabase.storage.from_(Config.SUPABASE_BUCKET).upload(
            path=file_path,
            file=file_bytes,
            file_options={
                "content-type": content_type,
                "cache-control": "3600"
            }
        )

        upload_error = None
        if isinstance(upload_result, dict):
            upload_error = upload_result.get('error') or upload_result.get('message')
        else:
            if hasattr(upload_result, 'error') and getattr(upload_result, 'error'):
                upload_error = str(getattr(upload_result, 'error'))
            elif hasattr(upload_result, 'status_code') and getattr(upload_result, 'status_code') and getattr(upload_result, 'status_code') >= 400:
                upload_error = f"HTTP {getattr(upload_result, 'status_code')}: {getattr(upload_result, 'text', None)}"

        if upload_error:
            raise RuntimeError(f"Supabase upload error: {upload_error}")

        signed_res = supabase.storage.from_(Config.SUPABASE_BUCKET).create_signed_url(file_path, 3600)
        if isinstance(signed_res, dict):
            signed_url = (
                signed_res.get('signedURL')
                or signed_res.get('signed_url')
                or signed_res.get('signedUrl')
                or signed_res.get('url')
            )
        else:
            signed_url = str(signed_res)


        return {
            "storage_path": file_path,
            "signed_url": signed_url,
        }
    except Exception as e:
        logger.error(f"Failed to upload to Supabase: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload to Supabase: {e}")


def update_memory_status(memory_id: str, status: str):

    try:
        supabase: Client = get_client()

        check_result = supabase.table('memories').select('id, user_id').eq('id', memory_id).execute()
        if not check_result.data:
            raise RuntimeError(f"No memory found with ID {memory_id}")

        result = supabase.table('memories').update({
            'status': status
        }).eq('id', memory_id).execute()


        return result.data
    except Exception as e:
        logger.error(f"Failed to update memory status for {memory_id}: {e}")
        raise


def update_memory_with_stl(memory_id: str, stl_storage_path: str):

    try:
        supabase: Client = get_client()

        check_result = supabase.table('memories').select('id, user_id').eq('id', memory_id).execute()
        if not check_result.data:
            raise RuntimeError(f"No memory found with ID {memory_id}")

        result = supabase.table('memories').update({
            'model_3d_url': stl_storage_path
        }).eq('id', memory_id).execute()


        return result.data
    except Exception as e:
        logger.error(f"Failed to update memory with STL for {memory_id}: {e}")
        raise


def get_figurine_url_from_memory(memory_id: str) -> str:

    try:
        supabase: Client = get_client()

        result = (
            supabase
            .table('memories')
            .select('id, user_id, figurine_url')
            .eq('id', memory_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail=f"Memory not found: {memory_id}")

        record = result.data[0]
        figurine_url = record.get('figurine_url')
        if not figurine_url:
            raise HTTPException(status_code=400, detail=f"figurine_url missing for memory: {memory_id}")


        return figurine_url
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch figurine URL for memory {memory_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch image from database")


