import base64
import logging
import time
from datetime import datetime

from fastapi import FastAPI, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from core.config import Config
from core.http import download_bytes_from_url
from core.middleware import log_requests, global_exception_handler
from core.validation import validate_inputs
from services.supabase_service import (
    create_signed_url_for_storage_object,
    get_figurine_url_from_memory,
    get_client,
    update_memory_status,
    update_memory_with_stl,
    upload_to_supabase,
)
from services.tencent_ai3d import generate_stl_from_image_base64, generate_stl_from_image_base64_async

logger = logging.getLogger(__name__)


def generate_stl_bytes(image_base64: str, enable_pbr: bool, request_id: str) -> bytes:
    """Generate STL bytes from image, using example.stl in development mode.
    
    Args:
        image_base64: Base64 encoded image data
        enable_pbr: Whether to enable PBR rendering
        request_id: Request identifier for logging
        
    Returns:
        STL file bytes
    """
    def _generate_with_ai3d() -> bytes:
        """Generate STL using Tencent AI3D service."""
        stl_bytes = generate_stl_from_image_base64(
            image_base64,
            enable_pbr=enable_pbr,
            poll_interval_seconds=5,
            timeout_seconds=300
        )
        return stl_bytes

    if Config.ENVIRONMENT == "development":
        try:
            with open("example.stl", "rb") as f:
                stl_bytes = f.read()
            return stl_bytes
        except FileNotFoundError:
            logger.error(f"[{request_id}] example.stl file not found, falling back to generation")
            return _generate_with_ai3d()
    else:
        return _generate_with_ai3d()


async def generate_stl_bytes_async(image_base64: str, enable_pbr: bool, request_id: str) -> bytes:
    """Async wrapper to generate STL bytes using Tencent service.
    In development mode, still returns local example file to keep parity.
    """
    async def _generate_with_ai3d_async() -> bytes:
        stl_bytes = await generate_stl_from_image_base64_async(
            image_base64,
            enable_pbr=enable_pbr,
            poll_interval_seconds=5,
            timeout_seconds=300
        )
        return stl_bytes

    if Config.ENVIRONMENT == "development":
        try:
            with open("example.stl", "rb") as f:
                stl_bytes = f.read()
            return stl_bytes
        except FileNotFoundError:
            logger.error(f"[{request_id}] example.stl file not found, falling back to generation")
            return await _generate_with_ai3d_async()
    else:
        return await _generate_with_ai3d_async()

# Initialize FastAPI
app = FastAPI(title="3D Generation API")

# CORS setup
ALLOWED_ORIGINS = Config.allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

@app.middleware("http")
async def _log_requests(request, call_next):
    return await log_requests(request, call_next)

@app.exception_handler(Exception)
async def _global_exception_handler(request, exc):
    return await global_exception_handler(request, exc)


@app.post("/generate-3d")
async def generate_3d(
    user_id: str = Form(None),
    memory_id: str = Form(None),
    enable_pbr: bool = Form(False)
):
    """Generate a 3D STL from the memory's figurine image.

    - Validates inputs and configuration
    - Fetches the figurine image from Supabase (signed URL)
    - Calls Tencent AI3D to generate an STL
    - Uploads the STL back to Supabase and updates the memory
    """
    request_start_time = time.time()
    request_id = f"3d-gen-{int(time.time() * 1000)}"
    

    try:
        # Validate configuration and inputs
        Config.validate()
        validate_inputs(user_id, memory_id)
        if not memory_id:
            logger.error(f"[{request_id}] Validation failed: memory_id is required")
            raise HTTPException(status_code=400, detail="memory_id is required")

        # Update memory status to processing_3d
        try:
            update_memory_status(memory_id, "processing_3d")
        except Exception as e:
            logger.warning(f"[{request_id}] Failed to update memory status: {e}")

        # Fetch and prepare image
        figurine_url = get_figurine_url_from_memory(memory_id)
        signed_url = create_signed_url_for_storage_object(figurine_url, expires_in_seconds=3600)
        image_bytes = download_bytes_from_url(signed_url)
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')

        # Generate STL (async non-blocking)
        stl_bytes = await generate_stl_bytes_async(image_base64, enable_pbr, request_id)

        # Generate filename and upload STL
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stl_filename = f"{memory_id + '_' if memory_id else ''}{timestamp}.stl"
        upload_info = upload_to_supabase(stl_bytes, stl_filename, content_type="model/stl", user_id=user_id)
        stl_storage_path = upload_info.get("storage_path") if isinstance(upload_info, dict) else None
        stl_signed_url = upload_info.get("signed_url") if isinstance(upload_info, dict) else None

        # Update memory record
        updated_memory = None
        if memory_id and stl_storage_path:
            try:
                updated_memory = update_memory_with_stl(memory_id, stl_storage_path)
            except Exception as e:
                logger.error(f"[{request_id}] Failed to update memory record: {e}")

        # Update memory status to completed
        if memory_id:
            try:
                update_memory_status(memory_id, "completed")
            except Exception as e:
                logger.warning(f"[{request_id}] Failed to update memory status: {e}")

        total_time = time.time() - request_start_time

        return {
            "status": "success",
            "message": "3D STL generated successfully",
            "stl_url": stl_signed_url,
            "stl_storage_path": stl_storage_path,
            "filename": stl_filename,
            "updated_memory": updated_memory
        }

    except HTTPException as e:
        total_time = time.time() - request_start_time
        logger.error(f"[{request_id}] Request failed ({e.status_code}): {e.detail} - Duration: {total_time:.1f}s")
        if memory_id:
            try:
                update_memory_status(memory_id, "failed")
            except Exception as status_e:
                logger.error(f"[{request_id}] Failed to update memory status: {status_e}")
        raise
    except Exception as e:
        total_time = time.time() - request_start_time
        logger.error(f"[{request_id}] Request failed: {str(e)} ({type(e).__name__}) - Duration: {total_time:.1f}s", exc_info=True)
        if memory_id:
            try:
                update_memory_status(memory_id, "failed")
            except Exception as status_e:
                logger.error(f"[{request_id}] Failed to update memory status: {status_e}")
        
        return {
            "status": "error",
            "message": str(e),
            "stl_url": None,
            "stl_storage_path": None,
            "filename": None,
            "updated_memory": None
        }


@app.get("/health")
async def health_check():
    """Basic health and dependency checks for the API."""
    health_start_time = time.time()
    
    try:
        # Check configuration and Supabase connection
        Config.validate()
        supabase = get_client()
        supabase.table('memories').select('id').limit(1).execute()
        
        health_duration = time.time() - health_start_time
        
        return {
            "status": "healthy",
            "service": "3d-generation-api",
            "timestamp": datetime.now().isoformat(),
            "response_time_ms": round(health_duration * 1000, 2)
        }
    except Exception as e:
        health_duration = time.time() - health_start_time
        logger.error(f"Health check failed: {str(e)} - Duration: {health_duration:.1f}s")
        
        return {
            "status": "unhealthy",
            "service": "3d-generation-api",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "response_time_ms": round(health_duration * 1000, 2)
        }


@app.get("/")
async def root():
    """Return basic API information."""
    
    return {
        "service": "3D Generation API",
        "version": "1.0",
        "endpoints": {
            "generate_3d": "/generate-3d",
            "health": "/health"
        },
        "timestamp": datetime.now().isoformat(),
        "description": "API for generating 3D STL files from images using Tencent AI3D service"
    }


