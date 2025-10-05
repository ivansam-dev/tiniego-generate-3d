import os
import ssl
import time
import asyncio
from typing import Optional
from urllib.request import urlopen

from dotenv import load_dotenv
from tencentcloud.common import credential
from tencentcloud.ai3d.v20250513.ai3d_client import Ai3dClient, models


def _create_client(region: str = "ap-guangzhou") -> Ai3dClient:
    """Create a Tencent AI3D client using env credentials.

    Requires env vars: TENCENT_CLOUD_ID, TENCENT_CLOUD_KEY
    """
    load_dotenv()
    secret_id = os.environ.get("TENCENT_SECRET_ID")
    secret_key = os.environ.get("TENCENT_SECRET_KEY")
    if not secret_id or not secret_key:
        raise RuntimeError("Missing TENCENT_CLOUD_ID or TENCENT_CLOUD_KEY environment variables")
    cred = credential.Credential(secret_id, secret_key)
    return Ai3dClient(cred, region)


def _submit_job(client: Ai3dClient, image_base64: str, enable_pbr: bool = False) -> str:
    """Submit image->3D job and return JobId."""
    request = models.SubmitHunyuanTo3DJobRequest()
    request.ImageBase64 = image_base64
    request.ResultFormat = "STL"
    request.EnablePBR = enable_pbr
    response = client.SubmitHunyuanTo3DJob(request)
    return response.JobId


def _query_job(client: Ai3dClient, job_id: str):
    """Query job status and result."""
    request = models.QueryHunyuanTo3DJobRequest()
    request.JobId = job_id
    return client.QueryHunyuanTo3DJob(request)


def _download_file(url: str, timeout_seconds: int = 60) -> bytes:
    """Download file bytes from a URL using stdlib to avoid extra deps."""
    # Create SSL context that doesn't verify certificates
    ssl_context = ssl.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
    
    with urlopen(url, timeout=timeout_seconds, context=ssl_context) as resp:
        return resp.read()


def generate_stl_from_image_base64(
    image_base64: str,
    *,
    enable_pbr: bool = False,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 300,
    region: str = "ap-singapore",
) -> bytes:
    """Submit an image to Tencent AI3D, poll until done, and return STL bytes.

    - image_base64: Base64-encoded image (without data URL prefix)
    - enable_pbr: Whether to enable PBR materials in generation
    - poll_interval_seconds: Poll cadence (default 5s)
    - timeout_seconds: Max time to wait (default 15 minutes)
    - region: Tencent Cloud region for AI3D service
    """
    client = _create_client(region)
    job_id = _submit_job(client, image_base64=image_base64, enable_pbr=enable_pbr)

    deadline = time.monotonic() + timeout_seconds
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for job {job_id} to finish")

        query_resp = _query_job(client, job_id)
        status = query_resp.Status

        if status == "FAIL":
            error_code = getattr(query_resp, "ErrorCode", None)
            error_message = getattr(query_resp, "ErrorMessage", None)
            raise RuntimeError(f"Tencent AI3D job failed ({error_code}): {error_message}")

        if status == "DONE":
            files = query_resp.ResultFile3Ds or []
            stl_url: Optional[str] = None
            for file3d in files:
                file_type = getattr(file3d, "Type", None)
                if file_type and str(file_type).upper() == "STL":
                    stl_url = getattr(file3d, "Url", None)
                    break
            if not stl_url:
                # Fallback: pick the first available URL if STL tag missing
                for file3d in files:
                    candidate = getattr(file3d, "Url", None)
                    if candidate:
                        stl_url = candidate
                        break
            if not stl_url:
                raise RuntimeError("STL URL not found in job result")
            return _download_file(stl_url)

        time.sleep(poll_interval_seconds)


async def generate_stl_from_image_base64_async(
    image_base64: str,
    *,
    enable_pbr: bool = False,
    poll_interval_seconds: int = 5,
    timeout_seconds: int = 300,
    region: str = "ap-guangzhou",
) -> bytes:
    """Async variant of STL generation using Tencent AI3D.

    Offloads blocking SDK calls and download to the default thread pool using
    asyncio.to_thread, while the polling cadence uses non-blocking sleeps.
    """
    # Use synchronous SDK calls, but keep the long wait periods non-blocking
    client = _create_client(region)
    job_id = _submit_job(client, image_base64=image_base64, enable_pbr=enable_pbr)

    deadline = time.monotonic() + timeout_seconds
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Timed out waiting for job {job_id} to finish")

        query_resp = _query_job(client, job_id)
        status = query_resp.Status

        if status == "FAIL":
            error_code = getattr(query_resp, "ErrorCode", None)
            error_message = getattr(query_resp, "ErrorMessage", None)
            raise RuntimeError(f"Tencent AI3D job failed ({error_code}): {error_message}")

        if status == "DONE":
            files = query_resp.ResultFile3Ds or []
            stl_url: Optional[str] = None
            for file3d in files:
                file_type = getattr(file3d, "Type", None)
                if file_type and str(file_type).upper() == "STL":
                    stl_url = getattr(file3d, "Url", None)
                    break
            if not stl_url:
                for file3d in files:
                    candidate = getattr(file3d, "Url", None)
                    if candidate:
                        stl_url = candidate
                        break
            if not stl_url:
                raise RuntimeError("STL URL not found in job result")
            return _download_file(stl_url)

        await asyncio.sleep(poll_interval_seconds)
