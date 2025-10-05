import logging
import ssl
from urllib.request import urlopen

from fastapi import HTTPException


logger = logging.getLogger(__name__)


def download_bytes_from_url(url: str, timeout_seconds: int = 60) -> bytes:
    try:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        with urlopen(url, timeout=timeout_seconds, context=ssl_context) as resp:
            image_bytes = resp.read()

        return image_bytes
    except Exception as e:
        logger.error(f"Failed to download image from URL {url}: {str(e)}")
        raise HTTPException(status_code=400, detail="Failed to download image from URL")


