import pika
from pika.exceptions import AMQPConnectionError
import time
import json
from save_and_load_data import load_last_saved_json
import logging
import logging.config
import configparser

logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()

config = configparser.ConfigParser()
config.read('configs/app.conf')

data_dir = config.get('storage', 'data_directory')
products_dir = config.get('storage', 'products_sub_dir')


def send_message(message, retries=5, delay=1, host_name='rabbitmq'):
    """
    Send a message to RabbitMQ with retries if the server is unavailable.

    :param message: The message to send (as a dictionary).
    :param retries: Number of retry attempts.
    :param delay: Delay (in seconds) between retries.
    """
    if not host_name:
        host_name = 'rabbitmq'
    for attempt in range(retries):
        try:
            # connection = pika.BlockingConnection(pika.ConnectionParameters(host='localhost', port=5672))
            connection = pika.BlockingConnection(pika.ConnectionParameters(host=host_name, port=5672))
            channel = connection.channel()
            channel.queue_declare(queue='uzum_products')
            channel.basic_publish(exchange='', routing_key='uzum_products', body=json.dumps(message))
            logger.info('Data message is sent successfully')
            connection.close()
            break
        except AMQPConnectionError as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}. Attempt {attempt + 1} of {retries}")
            if attempt < retries - 1:
                time.sleep(delay * attempt)
            else:
                logger.error(f"Exceeded maximum retries. Message not sent")
                return False
    return True


def run_default(path="", name="", host_name='rabbitmq'):
    if path and name:
        message = load_last_saved_json(path, name)
        if message:
            logger.info('Loaded default product for messaging')
    if not message:
        message = {
            "platform": "UZUM",
            "data": [
                {
                    "id": 1106551,
                    "title": "IPhone 15 Pro/ProMax, 128/256 ГБ, 1 SIM/Dual SIM, чехол в подарок",
                    "brand": "Apple",
                    "category": {
                        "id": 15272,
                        "title": "Смартфоны Apple iPhone(iOS)",
                        "productAmount": 0,
                        "parent": {
                            "id": 12690,
                            "title": "Смартфоны",
                            "productAmount": 630,
                            "parent": {
                                "id": 10044,
                                "title": "Смартфоны и телефоны",
                                "productAmount": 7741,
                                "parent": {
                                    "id": 10020,
                                    "title": "Электроника",
                                    "productAmount": 24428,
                                    "parent": None
                                }
                            }
                        }
                    },
                    "rating": 4.9,
                    "reviewsAmount": 78,
                    "ordersAmount": 279,
                    "totalAvailableAmount": 21,
                    "url": "https://uzum.uz/ru/product/1106551",
                    "photo": "https://images.uzum.uz/cpq77l35qt1gj8dcbsgg/original.jpg",
                    "skuList": [
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -1,
                                        "title": "Черный",
                                        "value": "#000000"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986876,
                                        "title": "15 Pro 256 GB",
                                        "value": "15 Pro 256 GB"
                                    }
                                }
                            ],
                            "id": 3358000,
                            "availableAmount": 3,
                            "fullPrice": 21000000,
                            "purchasePrice": 15499000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -291,
                                        "title": "Серый металлик",
                                        "value": "#C9CDCF"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986877,
                                        "title": "15 Pro Max 256 GB",
                                        "value": "15 Pro Max 256 GB"
                                    }
                                }
                            ],
                            "id": 3358007,
                            "availableAmount": 3,
                            "fullPrice": 23000000,
                            "purchasePrice": 16799000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -127,
                                        "title": "Голубой",
                                        "value": "#659cee"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986875,
                                        "title": "15 Pro 128 GB",
                                        "value": "15 Pro 128 GB"
                                    }
                                }
                            ],
                            "id": 3357996,
                            "availableAmount": 0,
                            "fullPrice": 18000000,
                            "purchasePrice": 13999000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -291,
                                        "title": "Серый металлик",
                                        "value": "#C9CDCF"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986876,
                                        "title": "15 Pro 256 GB",
                                        "value": "15 Pro 256 GB"
                                    }
                                }
                            ],
                            "id": 3358006,
                            "availableAmount": 0,
                            "fullPrice": 21000000,
                            "purchasePrice": 15499000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -5,
                                        "title": "Белый",
                                        "value": "#ffffff"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986877,
                                        "title": "15 Pro Max 256 GB",
                                        "value": "15 Pro Max 256 GB"
                                    }
                                }
                            ],
                            "id": 3358004,
                            "availableAmount": 2,
                            "fullPrice": 23000000,
                            "purchasePrice": 16799000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -127,
                                        "title": "Голубой",
                                        "value": "#659cee"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986876,
                                        "title": "15 Pro 256 GB",
                                        "value": "15 Pro 256 GB"
                                    }
                                }
                            ],
                            "id": 3357997,
                            "availableAmount": 3,
                            "fullPrice": 21000000,
                            "purchasePrice": 15499000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -5,
                                        "title": "Белый",
                                        "value": "#ffffff"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986876,
                                        "title": "15 Pro 256 GB",
                                        "value": "15 Pro 256 GB"
                                    }
                                }
                            ],
                            "id": 3358003,
                            "availableAmount": 1,
                            "fullPrice": 21000000,
                            "purchasePrice": 15499000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -5,
                                        "title": "Белый",
                                        "value": "#ffffff"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986875,
                                        "title": "15 Pro 128 GB",
                                        "value": "15 Pro 128 GB"
                                    }
                                }
                            ],
                            "id": 3358002,
                            "availableAmount": 3,
                            "fullPrice": 18000000,
                            "purchasePrice": 13999000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -1,
                                        "title": "Черный",
                                        "value": "#000000"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986875,
                                        "title": "15 Pro 128 GB",
                                        "value": "15 Pro 128 GB"
                                    }
                                }
                            ],
                            "id": 3357999,
                            "availableAmount": 0,
                            "fullPrice": 18000000,
                            "purchasePrice": 13999000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -127,
                                        "title": "Голубой",
                                        "value": "#659cee"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986877,
                                        "title": "15 Pro Max 256 GB",
                                        "value": "15 Pro Max 256 GB"
                                    }
                                }
                            ],
                            "id": 3357998,
                            "availableAmount": 1,
                            "fullPrice": 23000000,
                            "purchasePrice": 16799000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -291,
                                        "title": "Серый металлик",
                                        "value": "#C9CDCF"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986875,
                                        "title": "15 Pro 128 GB",
                                        "value": "15 Pro 128 GB"
                                    }
                                }
                            ],
                            "id": 3358005,
                            "availableAmount": 0,
                            "fullPrice": 18000000,
                            "purchasePrice": 13999000
                        },
                        {
                            "characteristics": [
                                {
                                    "id": -1,
                                    "title": "Цвет",
                                    "values": {
                                        "id": -1,
                                        "title": "Черный",
                                        "value": "#000000"
                                    }
                                },
                                {
                                    "id": 5986874,
                                    "title": "Модель",
                                    "values": {
                                        "id": 5986877,
                                        "title": "15 Pro Max 256 GB",
                                        "value": "15 Pro Max 256 GB"
                                    }
                                }
                            ],
                            "id": 3358001,
                            "availableAmount": 5,
                            "fullPrice": 23000000,
                            "purchasePrice": 16799000
                        }
                    ],
                    "seller": [
                        {
                            "id": 47249,
                            "title": "iMac Store",
                            "rating": 4.9,
                            "reviews": 108,
                            "orders": 393
                        }
                    ]
                }
            ]
        }
    return send_message(message, host_name=host_name)


if __name__ == '__main__':
    run_default()
