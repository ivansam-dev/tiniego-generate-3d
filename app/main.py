import uvicorn
import logging
from app import app

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
