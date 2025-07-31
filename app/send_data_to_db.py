import pika
from pika.exceptions import AMQPConnectionError
import time
import json
from save_and_load_data import load_last_saved_json
import logging
import logging.config
import configparser
import os
import redis

# Configuration and initialization with proper error handling
current_dir = os.path.dirname(os.path.abspath(__file__))
logging_config_path = os.path.join(current_dir, 'configs', 'logging.conf')
config_path = os.path.join(current_dir, 'configs', 'app.conf')

# Configure logging with fallback
try:
    if os.path.exists(logging_config_path):
        logging.config.fileConfig(logging_config_path)
        logger = logging.getLogger('broker_util')
    else:
        raise FileNotFoundError(f"Logging config not found: {logging_config_path}")
except Exception as e:
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    logger = logging.getLogger('broker_util')
    logger.warning(f"Could not load logging config: {e}. Using default configuration.")

# Load and validate configuration
config = configparser.ConfigParser()
try:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    config.read(config_path)

    # Validate required configuration sections and keys
    required_sections = {'broker': ['host', 'port']}

    for section, keys in required_sections.items():
        if not config.has_section(section):
            raise configparser.NoSectionError(f"Missing required config section: {section}")

        for key in keys:
            if not config.has_option(section, key):
                raise configparser.NoOptionError(f"Missing required config option: {section}.{key}", section, key)

    broker_host = config.get('broker', 'host')
    broker_port = config.get('broker', 'port')

    # Validate broker configuration
    if not broker_host or not broker_host.strip():
        raise ValueError("Broker host cannot be empty")

    try:
        broker_port_int = int(broker_port)
        if broker_port_int <= 0 or broker_port_int > 65535:
            raise ValueError(f"Invalid broker port: {broker_port}. Must be 1-65535.")
    except ValueError as e:
        raise ValueError(f"Broker port must be a valid integer: {broker_port}")

    logger.info(f"Configuration loaded successfully: broker={broker_host}:{broker_port}")

except Exception as e:
    logger.error(f"Configuration loading failed: {e}")
    # Set safe defaults and continue with warning
    broker_host = 'rabbitmq'
    broker_port = '5672'
    logger.warning(f"Using default broker configuration: {broker_host}:{broker_port}")

# Initialize Redis client with proper error handling
try:
    redis_host = os.getenv('REDIS_HOST', 'redis')
    redis_port = int(os.getenv('REDIS_PORT', '6379'))
    redis_db = int(os.getenv('REDIS_DB', '0'))

    redis_client = redis.StrictRedis(
        host=redis_host,
        port=redis_port,
        db=redis_db,
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True
    )

    # Test Redis connection
    redis_client.ping()
    logger.info(f"Redis connection established: {redis_host}:{redis_port}/{redis_db}")

except Exception as e:
    logger.error(f"Redis connection failed: {e}")
    logger.warning("Redis functionality may be limited")
    redis_client = None


def send_message_broker(message, retries=5, delay=1, host=broker_host, port=broker_port, queue_name="uzum_products"):
    """
    Send a message to RabbitMQ with retries and exponential backoff.

    :param message: The message to send (as a dictionary).
    :param retries: Number of retry attempts.
    :param delay: Initial delay (in seconds) between retries.
    :param host: RabbitMQ host.
    :param port: RabbitMQ port.
    :param queue_name: Target queue name.
    :return: True if message sent successfully, False otherwise.
    """
    # Input validation
    if message is None:
        logger.error("Cannot send None message to RabbitMQ")
        return False

    if not isinstance(message, (dict, list, str, int, float, bool)):
        logger.error(f"Invalid message type: {type(message)}. Must be JSON serializable.")
        return False

    # Validate message structure for dict messages
    if isinstance(message, dict) and 'data' in message and not message['data']:
        logger.warning("Message contains empty data, skipping RabbitMQ send")
        return True

    # Validate connection parameters
    if not host or not str(port).isdigit():
        logger.error(f"Invalid connection parameters: host='{host}', port='{port}'")
        return False

    connection = None
    for attempt in range(retries):
        try:
            # Validate credentials
            rabbitmq_user = os.getenv("RABBITMQ_USER")
            rabbitmq_password = os.getenv("RABBITMQ_PASSWORD")

            if not rabbitmq_user or not rabbitmq_password:
                logger.error("Missing RabbitMQ credentials in environment variables")
                return False

            logger.debug(f"Attempting to connect to RabbitMQ at {host}:{port} (attempt {attempt + 1}/{retries})")

            credentials = pika.PlainCredentials(rabbitmq_user, rabbitmq_password)
            connection_params = pika.ConnectionParameters(
                host=host,
                port=int(port),
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300
            )

            connection = pika.BlockingConnection(connection_params)
            channel = connection.channel()

            # Declare queue with error handling
            channel.queue_declare(queue=queue_name, durable=True)

            # Serialize message with error handling
            try:
                message_body = json.dumps(message, ensure_ascii=False)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to serialize message to JSON: {e}")
                return False

            # Publish message
            channel.basic_publish(
                exchange='',
                routing_key=queue_name,
                body=message_body,
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Make message persistent
                    timestamp=int(time.time())
                )
            )

            logger.info(f"Message successfully sent to queue '{queue_name}' (size: {len(message_body)} bytes)")
            break
        except AMQPConnectionError as e:
            logger.warning(f"RabbitMQ connection failed: {e}. Attempt {attempt + 1}/{retries}")
            logger.debug(f"Connection details: {host}:{port}")

            if attempt < retries - 1:
                # Exponential backoff with jitter
                backoff_time = min(delay * (2 ** attempt), 60)  # Cap at 60 seconds
                logger.info(f"Retrying in {backoff_time} seconds...")
                time.sleep(backoff_time)
            else:
                logger.error(f"Exceeded maximum retries ({retries}). Message not sent to RabbitMQ")
                return False

        except pika.exceptions.AMQPChannelError as e:
            logger.error(f"RabbitMQ channel error: {e}")
            return False

        except (json.JSONEncodeError, TypeError, ValueError) as e:
            logger.error(f"Message serialization error: {e}")
            return False

        except Exception as e:
            logger.error(f"Unexpected error sending message to RabbitMQ {host}:{port}: {e}")
            logger.debug(f"Message type: {type(message)}, Queue: {queue_name}")
            return False

        finally:
            # Ensure connection is properly closed
            if connection and not connection.is_closed:
                try:
                    connection.close()
                    logger.debug("RabbitMQ connection closed")
                except Exception as e:
                    logger.warning(f"Error closing RabbitMQ connection: {e}")
    return True


def send_message_redis(key, value, expiry_seconds=None) -> bool:
    """
    Send data to Redis with proper error handling and validation.

    :param key: Redis key (must be string)
    :param value: Value to store (will be converted to string)
    :param expiry_seconds: Optional expiration time in seconds
    :return: True if successful, False otherwise
    """
    # Check if Redis client is available
    if redis_client is None:
        logger.error("Redis client not available. Cannot send message.")
        return False

    # Input validation
    if not key or not isinstance(key, str):
        logger.error(f"Invalid Redis key: {key}. Must be non-empty string.")
        return False

    if value is None:
        logger.warning(f"Attempting to set None value for key '{key}'. Skipping.")
        return False

    try:
        # Convert value to string if it's not already
        if not isinstance(value, str):
            try:
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False)
                else:
                    value = str(value)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to serialize value for Redis key '{key}': {e}")
                return False

        # Set value with optional expiry
        if expiry_seconds:
            redis_client.setex(key, expiry_seconds, value)
            logger.debug(f"Set Redis key '{key}' with {expiry_seconds}s expiry")
        else:
            redis_client.set(key, value)
            logger.debug(f"Set Redis key '{key}' (no expiry)")

        return True

    except redis.ConnectionError as e:
        logger.error(f"Redis connection error for key '{key}': {e}")
        return False

    except redis.TimeoutError as e:
        logger.error(f"Redis timeout error for key '{key}': {e}")
        return False

    except redis.RedisError as e:
        logger.error(f"Redis error for key '{key}': {e}")
        return False

    except Exception as e:
        logger.error(f"Unexpected error setting Redis key '{key}': {e}")
        logger.debug(f"Value type: {type(value)}, Value length: {len(str(value))}")
        return False


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
    return send_message_broker(message, host=host, port=port)


if __name__ == '__main__':
    run_default()
