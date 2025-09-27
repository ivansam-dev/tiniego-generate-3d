import base64
import os
import re
import logging
import time
from io import BytesIO
from typing import Optional
import ssl
from urllib.request import urlopen
from urllib.parse import urlparse

from fastapi import FastAPI, UploadFile, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

from generate_3d_file import generate_stl_from_image_base64

# Load .env file
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI(title="3D Generation API")

# CORS setup
ALLOWED_ORIGINS_ENV = os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:3000")
ALLOWED_ORIGINS = [o.strip() for o in ALLOWED_ORIGINS_ENV.split(",") if o.strip()]

# Add Cloud Run origins automatically
ALLOWED_ORIGINS.extend([
    "https://tinymems-frontend-1099497855655.us-central1.run.app",  # Replace with your actual frontend URL
    "https://tinymems-frontend-1099497855655.us-central1.run.app/",  # With trailing slash
    "https://tiniego.com",  # New frontend domain
    "https://tiniego.com/",  # With trailing slash
    "https://www.tiniego.com",  # With www prefix
    "https://www.tiniego.com/",  # With www prefix and trailing slash
])

@app.middleware("http")
async def add_cors_headers(request: Request, call_next):
    response = await call_next(request)
    origin = request.headers.get("origin")
    if origin and origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Request logging
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    request_id = f"{int(time.time() * 1000)}-{id(request)}"
    
    logger.info(f"[{request_id}] === REQUEST STARTED ===")
    logger.info(f"[{request_id}] Method: {request.method}")
    logger.info(f"[{request_id}] URL: {request.url}")
    logger.info(f"[{request_id}] Client IP: {request.client.host if request.client else 'unknown'}")
    logger.info(f"[{request_id}] User-Agent: {request.headers.get('user-agent', 'unknown')}")
    logger.info(f"[{request_id}] Origin: {request.headers.get('origin', 'unknown')}")
    logger.info(f"[{request_id}] Content-Type: {request.headers.get('content-type', 'unknown')}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        logger.info(f"[{request_id}] === REQUEST COMPLETED ===")
        logger.info(f"[{request_id}] Status: {response.status_code}")
        logger.info(f"[{request_id}] Duration: {process_time:.3f}s")
        logger.info(f"[{request_id}] Response Headers: {dict(response.headers)}")
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"[{request_id}] === REQUEST FAILED ===")
        logger.error(f"[{request_id}] Error: {str(e)}")
        logger.error(f"[{request_id}] Duration: {process_time:.3f}s")
        raise

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = f"{int(time.time() * 1000)}-{id(request)}"
    logger.error(f"[{request_id}] === GLOBAL EXCEPTION HANDLER ===")
    logger.error(f"[{request_id}] Exception Type: {type(exc).__name__}")
    logger.error(f"[{request_id}] Exception Message: {str(exc)}")
    logger.error(f"[{request_id}] Request URL: {request.url}")
    logger.error(f"[{request_id}] Request Method: {request.method}")
    logger.error(f"[{request_id}] Stack Trace:", exc_info=True)
    
    origin = request.headers.get("origin")
    response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    if origin and origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "*"
    
    logger.error(f"[{request_id}] Returning 500 error to client")
    return response

# Config
class Config:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
    SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "memory-photos")

    @classmethod
    def validate(cls):
        if not cls.SUPABASE_URL:
            raise ValueError("SUPABASE_URL environment variable is required")
        if not cls.SUPABASE_ANON_KEY:
            raise ValueError("SUPABASE_ANON_KEY environment variable is required")
        if not cls.SUPABASE_SERVICE_KEY:
            raise ValueError("SUPABASE_SERVICE_KEY environment variable is required")

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp'}


def validate_file(file: UploadFile) -> None:
    logger.info(f"=== FILE VALIDATION STARTED ===")
    logger.info(f"Filename: {file.filename}")
    logger.info(f"File size: {getattr(file, 'size', 'unknown')} bytes")
    logger.info(f"Content type: {file.content_type}")
    logger.info(f"Max allowed size: {MAX_FILE_SIZE // (1024*1024)}MB")
    
    if getattr(file, 'size', None) and file.size > MAX_FILE_SIZE:
        logger.error(f"File validation failed: File too large ({file.size} bytes > {MAX_FILE_SIZE} bytes)")
        raise HTTPException(status_code=413, detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")
    
    if not file.filename:
        logger.error("File validation failed: No filename provided")
        raise HTTPException(status_code=400, detail="No filename provided")
    
    file_ext = os.path.splitext(file.filename.lower())[1]
    logger.info(f"File extension: {file_ext}")
    
    if file_ext not in ALLOWED_EXTENSIONS:
        logger.error(f"File validation failed: Invalid file type {file_ext}. Allowed: {ALLOWED_EXTENSIONS}")
        raise HTTPException(status_code=400, detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    
    if file.content_type not in ALLOWED_MIME_TYPES:
        logger.error(f"File validation failed: Invalid MIME type {file.content_type}. Allowed: {ALLOWED_MIME_TYPES}")
        raise HTTPException(status_code=400, detail=f"Invalid MIME type. Allowed: {', '.join(ALLOWED_MIME_TYPES)}")
    
    if '..' in file.filename or '/' in file.filename or '\\' in file.filename:
        logger.error(f"File validation failed: Invalid filename with path traversal characters: {file.filename}")
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    logger.info("=== FILE VALIDATION PASSED ===")


def validate_inputs(user_id: str = None, memory_id: str = None) -> None:
    logger.info(f"=== INPUT VALIDATION STARTED ===")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Memory ID: {memory_id}")
    
    if user_id and not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
        logger.error(f"Input validation failed: Invalid user_id format: {user_id}")
        raise HTTPException(status_code=400, detail="Invalid user_id format")
    
    if memory_id and not re.match(r'^[a-zA-Z0-9_-]+$', memory_id):
        logger.error(f"Input validation failed: Invalid memory_id format: {memory_id}")
        raise HTTPException(status_code=400, detail="Invalid memory_id format")
    
    logger.info("=== INPUT VALIDATION PASSED ===")


def upload_to_supabase(file_bytes: bytes, filename: str, content_type: str, user_id: Optional[str] = None):
    upload_start_time = time.time()
    logger.info(f"=== SUPABASE UPLOAD STARTED ===")
    logger.info(f"Filename: {filename}")
    logger.info(f"Content type: {content_type}")
    logger.info(f"File size: {len(file_bytes)} bytes")
    logger.info(f"User ID: {user_id}")
    logger.info(f"Bucket: {Config.SUPABASE_BUCKET}")
    
    try:
        logger.info("Creating Supabase client...")
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        
        # Use 3d-models folder and keep path as canonical identifier
        if user_id:
            file_path = f"{user_id}/3d-models/{filename}"
        else:
            file_path = f"generated/3d-models/{filename}"
        
        logger.info(f"File path: {file_path}")
        
        # Upload file to Supabase
        logger.info("Uploading file to Supabase storage...")
        upload_result = supabase.storage.from_(Config.SUPABASE_BUCKET).upload(
            path=file_path,
            file=file_bytes,
            file_options={
                "content-type": content_type,
                "cache-control": "3600"
            }
        )
        
        logger.info(f"Upload result type: {type(upload_result)}")
        logger.info(f"Upload result: {upload_result}")
        
        # Check for upload errors
        upload_error = None
        if isinstance(upload_result, dict):
            upload_error = upload_result.get('error') or upload_result.get('message')
            logger.info(f"Upload result is dict, checking for errors...")
        else:
            logger.info(f"Upload result is {type(upload_result)}, checking attributes...")
            if hasattr(upload_result, 'error') and getattr(upload_result, 'error'):
                upload_error = str(getattr(upload_result, 'error'))
                logger.error(f"Upload error found: {upload_error}")
            elif hasattr(upload_result, 'status_code') and getattr(upload_result, 'status_code') and getattr(upload_result, 'status_code') >= 400:
                upload_error = f"HTTP {getattr(upload_result, 'status_code')}: {getattr(upload_result, 'text', None)}"
                logger.error(f"Upload HTTP error: {upload_error}")
        
        if upload_error:
            logger.error(f"Upload failed with error: {upload_error}")
            raise RuntimeError(f"Supabase upload error: {upload_error}")
        
        logger.info("Upload successful, creating signed URL...")
        # Prefer a signed URL (bucket can remain private)
        signed_res = supabase.storage.from_(Config.SUPABASE_BUCKET).create_signed_url(file_path, 3600)
        logger.info(f"Signed URL result type: {type(signed_res)}")
        logger.info(f"Signed URL result: {signed_res}")
        if isinstance(signed_res, dict):
            signed_url = (
                signed_res.get('signedURL')
                or signed_res.get('signed_url')
                or signed_res.get('signedUrl')
                or signed_res.get('url')
            )
        else:
            signed_url = str(signed_res)
        
        upload_duration = time.time() - upload_start_time
        logger.info(f"=== SUPABASE UPLOAD COMPLETED ===")
        logger.info(f"Storage path: {file_path}")
        logger.info(f"Signed URL: {signed_url}")
        logger.info(f"Upload duration: {upload_duration:.3f}s")
        
        return {
            "storage_path": file_path,
            "signed_url": signed_url,
        }
    except Exception as e:
        upload_duration = time.time() - upload_start_time
        logger.error(f"=== SUPABASE UPLOAD FAILED ===")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Upload duration: {upload_duration:.3f}s")
        logger.error(f"Exception type: {type(e).__name__}")
        raise HTTPException(status_code=500, detail=f"Failed to upload to Supabase: {e}")


def update_memory_status(memory_id: str, status: str):
    update_start_time = time.time()
    logger.info(f"=== MEMORY STATUS UPDATE STARTED ===")
    logger.info(f"Memory ID: {memory_id}")
    logger.info(f"Status: {status}")
    
    try:
        logger.info("Creating Supabase client...")
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        
        logger.info(f"Checking if memory exists: {memory_id}")
        check_result = supabase.table('memories').select('id, user_id').eq('id', memory_id).execute()
        logger.info(f"Memory check result: {check_result}")
        
        if not check_result.data:
            logger.error(f"Memory not found: {memory_id}")
            raise RuntimeError(f"No memory found with ID {memory_id}")
        
        logger.info(f"Memory found, updating status to {status}...")
        result = supabase.table('memories').update({
            'status': status
        }).eq('id', memory_id).execute()
        
        update_duration = time.time() - update_start_time
        logger.info(f"=== MEMORY STATUS UPDATE COMPLETED ===")
        logger.info(f"Updated records: {len(result.data) if result.data else 0}")
        logger.info(f"Update duration: {update_duration:.3f}s")
        
        return result.data
    except Exception as e:
        update_duration = time.time() - update_start_time
        logger.error(f"=== MEMORY STATUS UPDATE FAILED ===")
        logger.error(f"Memory ID: {memory_id}")
        logger.error(f"Status: {status}")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Update duration: {update_duration:.3f}s")
        logger.error(f"Exception type: {type(e).__name__}")
        raise


def update_memory_with_stl(memory_id: str, stl_storage_path: str):
    update_start_time = time.time()
    logger.info(f"=== MEMORY UPDATE STARTED ===")
    logger.info(f"Memory ID: {memory_id}")
    logger.info(f"STL storage path: {stl_storage_path}")
    
    try:
        logger.info("Creating Supabase client...")
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        
        logger.info(f"Checking if memory exists: {memory_id}")
        check_result = supabase.table('memories').select('id, user_id').eq('id', memory_id).execute()
        logger.info(f"Memory check result: {check_result}")
        
        if not check_result.data:
            logger.error(f"Memory not found: {memory_id}")
            raise RuntimeError(f"No memory found with ID {memory_id}")
        
        logger.info(f"Memory found, updating with STL storage path...")
        result = supabase.table('memories').update({
            'model_3d_url': stl_storage_path
        }).eq('id', memory_id).execute()
        
        update_duration = time.time() - update_start_time
        logger.info(f"=== MEMORY UPDATE COMPLETED ===")
        logger.info(f"Updated records: {len(result.data) if result.data else 0}")
        logger.info(f"Update duration: {update_duration:.3f}s")
        
        return result.data
    except Exception as e:
        update_duration = time.time() - update_start_time
        logger.error(f"=== MEMORY UPDATE FAILED ===")
        logger.error(f"Memory ID: {memory_id}")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Update duration: {update_duration:.3f}s")
        logger.error(f"Exception type: {type(e).__name__}")
        raise


def get_figurine_url_from_memory(memory_id: str) -> str:
    fetch_start_time = time.time()
    logger.info(f"=== FETCH FIGURINE URL STARTED ===")
    logger.info(f"Memory ID: {memory_id}")
    
    try:
        logger.info("Creating Supabase client...")
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        
        logger.info(f"Querying memory record for ID: {memory_id}")
        result = (
            supabase
            .table('memories')
            .select('id, user_id, figurine_url')
            .eq('id', memory_id)
            .execute()
        )
        
        logger.info(f"Query result: {result}")
        logger.info(f"Records found: {len(result.data) if result.data else 0}")
        
        if not result.data:
            logger.error(f"Memory not found: {memory_id}")
            raise HTTPException(status_code=404, detail=f"Memory not found: {memory_id}")
        
        record = result.data[0]
        logger.info(f"Memory record: {record}")
        
        figurine_url = record.get('figurine_url')
        logger.info(f"Figurine URL: {figurine_url}")
        
        if not figurine_url:
            logger.error(f"figurine_url missing for memory: {memory_id}")
            raise HTTPException(status_code=400, detail=f"figurine_url missing for memory: {memory_id}")
        
        fetch_duration = time.time() - fetch_start_time
        logger.info(f"=== FETCH FIGURINE URL COMPLETED ===")
        logger.info(f"Figurine URL: {figurine_url}")
        logger.info(f"Fetch duration: {fetch_duration:.3f}s")
        
        return figurine_url
    except HTTPException:
        fetch_duration = time.time() - fetch_start_time
        logger.error(f"=== FETCH FIGURINE URL FAILED (HTTPException) ===")
        logger.error(f"Memory ID: {memory_id}")
        logger.error(f"Fetch duration: {fetch_duration:.3f}s")
        raise
    except Exception as e:
        fetch_duration = time.time() - fetch_start_time
        logger.error(f"=== FETCH FIGURINE URL FAILED ===")
        logger.error(f"Memory ID: {memory_id}")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Fetch duration: {fetch_duration:.3f}s")
        logger.error(f"Exception type: {type(e).__name__}")
        raise HTTPException(status_code=500, detail="Failed to fetch image from database")


def _infer_storage_path_from_url(url_or_path: str, bucket: str) -> str:
    """Infer the storage object path within the given bucket from a URL or path.

    Supports:
    - Raw paths like "user123/figurines/file.png"
    - Public URLs like 
      "https://<project>.supabase.co/storage/v1/object/public/<bucket>/user123/figurines/file.png"
    - Auth/signed/object URLs like
      "/storage/v1/object/(sign|auth)?/<bucket>/..."
    """
    if not url_or_path:
        raise HTTPException(status_code=400, detail="Empty figurine URL/path")

    # If it's not an absolute URL, treat it as already a storage path
    if '://' not in url_or_path:
        return url_or_path.lstrip('/')

    parsed = urlparse(url_or_path)
    # Extract segments and find the bucket segment, then return the rest as path
    segments = [seg for seg in parsed.path.split('/') if seg]
    # Try to find the bucket segment to the path after /storage/v1/object/.../<bucket>/...
    try:
        bucket_index = segments.index(bucket)
        relative_segments = segments[bucket_index + 1:]
        if not relative_segments:
            raise ValueError("No object path after bucket")
        return '/'.join(relative_segments)
    except ValueError:
        # If bucket not found, return original path minus leading slash as fallback
        return parsed.path.lstrip('/')


def create_signed_url_for_storage_object(url_or_path: str, *, expires_in_seconds: int = 3600) -> str:
    """Create a signed URL for an object stored in Supabase Storage.

    - Accepts either a full Supabase storage URL or a bucket-relative path.
    - Returns a signed URL that is valid for the given expiration.
    """
    try:
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        object_path = _infer_storage_path_from_url(url_or_path, Config.SUPABASE_BUCKET)
        signed_result = supabase.storage.from_(Config.SUPABASE_BUCKET).create_signed_url(
            object_path,
            expires_in_seconds
        )

        # Handle various return shapes from supabase-py
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


def download_bytes_from_url(url: str, timeout_seconds: int = 60) -> bytes:
    download_start_time = time.time()
    logger.info(f"=== IMAGE DOWNLOAD STARTED ===")
    logger.info(f"URL: {url}")
    logger.info(f"Timeout: {timeout_seconds}s")
    
    try:
        logger.info("Creating SSL context...")
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        logger.info("Downloading image...")
        with urlopen(url, timeout=timeout_seconds, context=ssl_context) as resp:
            image_bytes = resp.read()
            
        download_duration = time.time() - download_start_time
        logger.info(f"=== IMAGE DOWNLOAD COMPLETED ===")
        logger.info(f"Downloaded size: {len(image_bytes)} bytes")
        logger.info(f"Download duration: {download_duration:.3f}s")
        
        return image_bytes
    except Exception as e:
        download_duration = time.time() - download_start_time
        logger.error(f"=== IMAGE DOWNLOAD FAILED ===")
        logger.error(f"URL: {url}")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Download duration: {download_duration:.3f}s")
        logger.error(f"Exception type: {type(e).__name__}")
        raise HTTPException(status_code=400, detail="Failed to download image from URL")


@app.post("/generate-3d")
async def generate_3d(
    user_id: str = Form(None),
    memory_id: str = Form(None),
    enable_pbr: bool = Form(False)
):
    request_start_time = time.time()
    request_id = f"3d-gen-{int(time.time() * 1000)}"
    
    logger.info(f"[{request_id}] === 3D GENERATION REQUEST STARTED ===")
    logger.info(f"[{request_id}] User ID: {user_id}")
    logger.info(f"[{request_id}] Memory ID: {memory_id}")
    logger.info(f"[{request_id}] Enable PBR: {enable_pbr}")
    logger.info(f"[{request_id}] Request timestamp: {datetime.now().isoformat()}")

    try:
        # Validate configuration
        logger.info(f"[{request_id}] Validating configuration...")
        Config.validate()
        logger.info(f"[{request_id}] Configuration validation passed")

        # Validate inputs
        logger.info(f"[{request_id}] Validating input parameters...")
        validate_inputs(user_id, memory_id)
        if not memory_id:
            logger.error(f"[{request_id}] Validation failed: memory_id is required")
            raise HTTPException(status_code=400, detail="memory_id is required")
        logger.info(f"[{request_id}] Input validation passed")

        # Update memory status to processing_3d
        logger.info(f"[{request_id}] Updating memory status to processing_3d...")
        try:
            update_memory_status(memory_id, "processing_3d")
            logger.info(f"[{request_id}] Memory status updated successfully")
        except Exception as e:
            logger.error(f"[{request_id}] Failed to update memory status: {e}")
            logger.error(f"[{request_id}] Continuing with 3D generation...")

        # Fetch image URL from Supabase and download the image
        logger.info(f"[{request_id}] Fetching figurine URL from database...")
        figurine_url = get_figurine_url_from_memory(memory_id)
        logger.info(f"[{request_id}] Figurine URL retrieved: {figurine_url}")

        # Generate signed URL and download image
        logger.info(f"[{request_id}] Creating signed URL for image...")
        signed_url = create_signed_url_for_storage_object(figurine_url, expires_in_seconds=3600)
        logger.info(f"[{request_id}] Signed URL created")

        logger.info(f"[{request_id}] Downloading image via signed URL...")
        image_bytes = download_bytes_from_url(signed_url)
        logger.info(f"[{request_id}] Image downloaded: {len(image_bytes)} bytes")
        
        # Convert to base64
        logger.info(f"[{request_id}] Converting image to base64...")
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        logger.info(f"[{request_id}] Image converted to base64: {len(image_base64)} characters")

        # Generate STL
        logger.info(f"[{request_id}] === STARTING 3D GENERATION ===")
        logger.info(f"[{request_id}] Calling Tencent AI3D service...")
        logger.info(f"[{request_id}] PBR enabled: {enable_pbr}")
        logger.info(f"[{request_id}] Poll interval: 5s, Timeout: 300s")
        
        stl_generation_start = time.time()
        stl_bytes = generate_stl_from_image_base64(
            image_base64,
            enable_pbr=enable_pbr,
            poll_interval_seconds=5,
            timeout_seconds=300
        )
        stl_generation_duration = time.time() - stl_generation_start
        
        logger.info(f"[{request_id}] === 3D GENERATION COMPLETED ===")
        logger.info(f"[{request_id}] STL generated: {len(stl_bytes)} bytes")
        logger.info(f"[{request_id}] Generation duration: {stl_generation_duration:.3f}s")
        
        # use example.stl to test
        # stl_bytes = open("example.stl", "rb").read()

        # Generate filename
        logger.info(f"[{request_id}] Generating filename...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stl_filename = f"{memory_id + '_' if memory_id else ''}{timestamp}.stl"
        logger.info(f"[{request_id}] Filename: {stl_filename}")

        # Upload STL to Supabase
        logger.info(f"[{request_id}] Uploading STL to Supabase...")
        upload_info = upload_to_supabase(stl_bytes, stl_filename, content_type="model/stl", user_id=user_id)
        stl_storage_path = upload_info.get("storage_path") if isinstance(upload_info, dict) else None
        stl_signed_url = upload_info.get("signed_url") if isinstance(upload_info, dict) else None
        logger.info(f"[{request_id}] STL uploaded successfully. Storage path: {stl_storage_path}, signed URL present: {stl_signed_url is not None}")

        # Optionally update memory record
        updated_memory = None
        if memory_id:
            logger.info(f"[{request_id}] Updating memory record with STL storage path...")
            try:
                if stl_storage_path:
                    updated_memory = update_memory_with_stl(memory_id, stl_storage_path)
                    logger.info(f"[{request_id}] Memory record updated successfully")
                else:
                    logger.error(f"[{request_id}] Missing stl_storage_path, skipping DB update")
            except Exception as e:
                logger.error(f"[{request_id}] DB update failed for memory {memory_id}: {e}")
                logger.error(f"[{request_id}] Continuing without DB update...")
        else:
            logger.info(f"[{request_id}] No memory_id provided, skipping DB update")

        # Update memory status to completed
        if memory_id:
            logger.info(f"[{request_id}] Updating memory status to completed...")
            try:
                update_memory_status(memory_id, "completed")
                logger.info(f"[{request_id}] Memory status updated to completed successfully")
            except Exception as e:
                logger.error(f"[{request_id}] Failed to update memory status to completed: {e}")
                logger.error(f"[{request_id}] Continuing...")

        total_time = time.time() - request_start_time
        logger.info(f"[{request_id}] === 3D GENERATION REQUEST COMPLETED SUCCESSFULLY ===")
        logger.info(f"[{request_id}] Total duration: {total_time:.2f}s")
        logger.info(f"[{request_id}] STL storage path: {stl_storage_path}")
        logger.info(f"[{request_id}] Filename: {stl_filename}")
        logger.info(f"[{request_id}] Memory updated: {updated_memory is not None}")

        return {
            "status": "success",
            "message": "3D STL generated successfully",
            # Keep stl_url for backward compatibility (signed URL for display)
            "stl_url": stl_signed_url,
            "stl_storage_path": stl_storage_path,
            "filename": stl_filename,
            "updated_memory": updated_memory
        }

    except HTTPException as e:
        total_time = time.time() - request_start_time
        logger.error(f"[{request_id}] === 3D GENERATION REQUEST FAILED (HTTPException) ===")
        logger.error(f"[{request_id}] Status: {e.status_code}")
        logger.error(f"[{request_id}] Detail: {e.detail}")
        logger.error(f"[{request_id}] Duration: {total_time:.2f}s")
        if memory_id:
            logger.info(f"[{request_id}] Updating memory status to failed...")
            try:
                update_memory_status(memory_id, "failed")
                logger.info(f"[{request_id}] Memory status updated to failed successfully")
            except Exception as status_e:
                logger.error(f"[{request_id}] Failed to update memory status to failed: {status_e}")
        raise
    except Exception as e:
        total_time = time.time() - request_start_time
        logger.error(f"[{request_id}] === 3D GENERATION REQUEST FAILED ===")
        logger.error(f"[{request_id}] Error: {str(e)}")
        logger.error(f"[{request_id}] Exception type: {type(e).__name__}")
        logger.error(f"[{request_id}] Duration: {total_time:.2f}s")
        logger.error(f"[{request_id}] Stack trace:", exc_info=True)
        if memory_id:
            logger.info(f"[{request_id}] Updating memory status to failed...")
            try:
                update_memory_status(memory_id, "failed")
                logger.info(f"[{request_id}] Memory status updated to failed successfully")
            except Exception as status_e:
                logger.error(f"[{request_id}] Failed to update memory status to failed: {status_e}")
        
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
    health_start_time = time.time()
    logger.info("=== HEALTH CHECK REQUESTED ===")
    
    try:
        # Check configuration
        logger.info("Checking configuration...")
        Config.validate()
        logger.info("Configuration check passed")
        
        # Check Supabase connection
        logger.info("Checking Supabase connection...")
        supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_SERVICE_KEY)
        # Simple query to test connection
        test_result = supabase.table('memories').select('id').limit(1).execute()
        logger.info("Supabase connection check passed")
        
        health_duration = time.time() - health_start_time
        logger.info(f"=== HEALTH CHECK COMPLETED ===")
        logger.info(f"Status: healthy")
        logger.info(f"Duration: {health_duration:.3f}s")
        
        return {
            "status": "healthy",
            "service": "3d-generation-api",
            "timestamp": datetime.now().isoformat(),
            "response_time_ms": round(health_duration * 1000, 2)
        }
    except Exception as e:
        health_duration = time.time() - health_start_time
        logger.error(f"=== HEALTH CHECK FAILED ===")
        logger.error(f"Error: {str(e)}")
        logger.error(f"Duration: {health_duration:.3f}s")
        
        return {
            "status": "unhealthy",
            "service": "3d-generation-api",
            "timestamp": datetime.now().isoformat(),
            "error": str(e),
            "response_time_ms": round(health_duration * 1000, 2)
        }


@app.get("/")
async def root():
    logger.info("=== ROOT ENDPOINT REQUESTED ===")
    logger.info("Returning API information")
    
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


if __name__ == "__main__":
    import uvicorn
    
    logger.info("=== STARTING 3D GENERATION API ===")
    logger.info("Environment variables loaded")
    logger.info("Supabase integration enabled")
    logger.info("Tencent AI3D integration enabled")
    logger.info(f"Max file size: {MAX_FILE_SIZE // (1024*1024)}MB")
    logger.info(f"Allowed extensions: {ALLOWED_EXTENSIONS}")
    logger.info(f"Allowed MIME types: {ALLOWED_MIME_TYPES}")
    logger.info(f"CORS allowed origins: {len(ALLOWED_ORIGINS)} configured")
    logger.info("Starting server on 0.0.0.0:8080")
    
    uvicorn.run(app, host="0.0.0.0", port=8080)
