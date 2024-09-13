import os
import requests
import logging
# import logging.config

# logging.config.fileConfig('configs/logging.conf')
# logger = logging.getLogger()
# # Adjust the logging level for the console handler only for this specific module
# for handler in logger.handlers:
#     if isinstance(handler, logging.StreamHandler):  # Ensure we only modify the console handler
#         handler.setLevel(logging.WARNING)  # Set console output to WARNING and higher for this module

logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


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
