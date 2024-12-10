import os
import requests
import logging
import logging.config

import redis

# Create Redis client instance
redis_client = redis.StrictRedis(host='redis', port=6379, db=0)

# logging.config.fileConfig('configs/logging.conf')
# logger = logging.getLogger()
# # Adjust the logging level for the console handler only for this specific module
# for handler in logger.handlers:
#     if isinstance(handler, logging.StreamHandler):  # Ensure we only modify the console handler
#         handler.setLevel(logging.WARNING)  # Set console output to WARNING and higher for this module

BASE_URL = "http://barakadatauz-image_service-1:8000"

current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')

# Configure logging
try:
    logging.config.fileConfig(logging_config_path)
    logger = logging.getLogger('image_download')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")


def download_image(
        url: str,
        product_id: int,
        directory: str = 'images') -> str:
    if not os.path.exists(directory):
        os.makedirs(directory)

    image_path = os.path.join(directory, f"{product_id}.jpg")

    if os.path.exists(image_path):
        logger.warning(f"Image already exists: {image_path}")
        return image_path

    logger.info(f"Start to download image for product {product_id} from: {url}")
    response = requests.get(url, stream=True)

    try:
        if response.status_code == 200:
            with open(image_path, 'wb') as file:
                for chunk in response.iter_content(1024):
                    file.write(chunk)
            logger.info(f"Image downloaded: {image_path}")
        else:
            logger.error(f"Failed to download image for product {product_id}: {response.status_code}")
            raise Exception(f"Failed to download image: {response.status_code}")
    finally:
        response.close()  # Ensuring the connection is closed

    return image_path


def store_image_url_in_redis(product_id: str, image_url: str, expiration: int = 259200):  # Expiration = 3 days
    """
    Store the image URL in Redis with a key based on the product ID.
    """
    redis_key = f"product_image_{product_id}"
    try:
        redis_client.setex(redis_key, expiration, image_url)
        return True
    except Exception as e:
        logger.error(f"Error storing image URL in Redis: {e}")
        return False


def upload_image_from_url(
        image_url: str,
        object_key: str,
        image_category: str = "product"):
    url = f"{BASE_URL}/v1/image/upload-from-url"
    data = {
        "url": image_url,
        "image_category": image_category,
        "object_key": object_key
    }
    response = requests.post(url, json=data)
    if response.status_code == 200:
        logger.debug(f"Image {object_key} uploaded successfully.")
        res = response.json()
        product_id = object_key.split('_')[0]  # Extract product ID from object_key
        try:
            redis_stored = store_image_url_in_redis(product_id, res["url"])
            if redis_stored:
                logger.info(f"Redist stored: {object_key}")
            else:
                logger.warning(f"Failed to Redis store: {object_key}!")
        except Exception as e:
            logger.error(f"While storing Redis: {e}")
        return res
    else:
        logger.error(f"Error: {response.status_code}, {response.text}")
        return None
