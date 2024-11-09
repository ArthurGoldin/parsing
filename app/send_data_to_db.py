import pika
from pika.exceptions import AMQPConnectionError
import time
import json
from save_and_load_data import load_last_saved_json
import logging
import logging.config
import configparser
import os


current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

# Configure logging
try:
    logging.config.fileConfig(logging_config_path)
    logger = logging.getLogger('main')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

config = configparser.ConfigParser()
config.read(config_path)

broker_host = config.get('broker', 'host')
broker_port = config.get('broker', 'port')


def send_message(message, retries=5, delay=1, host=broker_host, port=broker_port):
    """
    Send a message to RabbitMQ with retries if the server is unavailable.

    :param message: The message to send (as a dictionary).
    :param retries: Number of retry attempts.
    :param delay: Delay (in seconds) between retries.
    :param host_name: rabbitmq for Docker implementation
    """
    # print(host)
    # if not host:
    #     host = 'rabbitmq'
    # print(host)
    for attempt in range(retries):
        try:
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=host, port=port))
            channel = connection.channel()
            channel.queue_declare(queue='uzum_products')
            channel.basic_publish(exchange='',
                                  routing_key='uzum_products',
                                  body=json.dumps(message))
            logger.debug('Message is sent')
            connection.close()
            break
        except AMQPConnectionError as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}. Attempt {attempt + 1} of {retries}")
            logger.debug(f"Host:{host}:{port}")
            if attempt < retries - 1:
                time.sleep(delay * attempt)
            else:
                logger.error(f"Exceeded maximum retries. Message not sent")
                return False
        except Exception as e:
            logger.error(f"Failed to send message to {host}: {e}")
            return False
    return True


def run_default(path="", name="", host=broker_host, port=broker_port):
    message = None
    if path and name:
        message = load_last_saved_json(path, name)
        if message:
            logger.info('Loaded default product for messaging')
    if not message:
        logger.warning('No JSON file loaded!')
        message = {
            "platform": "DEFAULT",
            "data": "DEFAULT"
        }
    return send_message(message, host=host, port=port)


if __name__ == '__main__':
    run_default()
