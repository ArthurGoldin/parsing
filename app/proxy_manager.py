from typing import List, Dict, Optional
import logging
import logging.config
import json
import requests
import random
from enum import Enum
import time

# Configure logging
try:
    logging.config.fileConfig('configs/logging.conf')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
finally:
    logger = logging.getLogger()


class ProxyStatus(Enum):
    """
    Enum representing the possible statuses of a proxy.

    Attributes:
        ACTIVE (str): Indicates the proxy is active.
        NOT_ACTIVE (str): Indicates the proxy is not active.
        UNDEFINED (str): Indicates the proxy status is undefined.
    """
    ACTIVE = 'ACTIVE'
    NOT_ACTIVE = 'NOT ACTIVE'
    UNDEFINED = 'UNDEFINED'

    @classmethod
    def _missing_(cls, value):
        """
        Overrides the default _missing_ method to handle invalid status values.
        Logs a warning and sets the status to UNDEFINED.

        Args:
            value (str): The invalid status value.

        Returns:
            ProxyStatus: The UNDEFINED status.
        """
        logger.warning(f"PROXY:: invalid status '{value}' for proxy, setting status to UNDEFINED")
        return cls.UNDEFINED


class Proxy:
    """
    Represents a proxy server configuration.

    Attributes:
        ip (str): The IP address of the proxy server.
        ports (Dict[str, int]): A dictionary mapping protocol names to their respective port numbers.
        user (str): Username for proxy authentication.
        password (str): Password for proxy authentication.
        proxy_address (Dict[str, str]): Additional address-related information for the proxy.
        exp (int): Expiration time or duration for the proxy.
        status (ProxyStatus): Current status of the proxy (e.g., 'ACTIVE', 'NOT ACTIVE').
    """

    def __init__(
        self,
        ip: str,
        ports: Dict[str, int],
        user: str,
        password: str,
        proxy_address: Dict[str, str],
        exp: int,
        status: ProxyStatus
    ):
        """
        Initializes a new instance of the Proxy class.

        Args:
            ip (str): The IP address of the proxy server.
            ports (Dict[str, int]): A dictionary mapping protocol names to their respective port numbers.
            user (str): Username for proxy authentication.
            password (str): Password for proxy authentication.
            proxy_address (Dict[str, str]): Additional address-related information for the proxy.
            exp (int): Expiration time or duration for the proxy.
            status (ProxyStatus): Current status of the proxy (e.g., 'ACTIVE', 'NOT ACTIVE').
        """
        self.ip = ip
        self.ports = ports
        self.user = user
        self.password = password
        self.proxy_address = proxy_address
        self.exp = exp
        self.status = status

    def is_active(self) -> bool:
        """
        Determines if the proxy is currently active.

        Returns:
            bool: True if the proxy status is ACTIVE, False otherwise.
        """
        return self.status == ProxyStatus.ACTIVE

    def is_expired(self) -> bool:
        """
        Checks if the proxy has expired based on the current time.

        Returns:
            bool: True if the current time is greater than the expiration time, False otherwise.
        """
        return time.time() > self.exp

    def set_status(self, status: ProxyStatus) -> bool:
        """
        Sets the status of the proxy to the specified value if it's a valid ProxyStatus.

        Args:
            status (ProxyStatus): The new status to set for the proxy.

        Returns:
            bool: True if the status was successfully updated, False otherwise.
        """
        if isinstance(status, ProxyStatus):
            self.status = status
            logger.info(f"PROXY:: status of {self.ip} changed to {status.value}")
            return True
        logger.error(f"PROXY:: wrong status value")
        return False

    def __repr__(self):
        """
        Returns a string representation of the Proxy instance, masking the password for security.

        Returns:
            str: A string representation of the Proxy instance.
        """
        return (
            f"Proxy(ip='{self.ip}', ports={self.ports}, user='{self.user}', "
            f"password='****', proxy_address={self.proxy_address}, "
            f"exp={self.exp}, status='{self.status.value}')"
        )


class ProxyManager:
    """
    Manages a collection of Proxy instances, providing functionalities to add, remove, and retrieve proxies.

    Attributes:
        proxies (List[Proxy]): A list that holds Proxy instances.
    """

    def __init__(self):
        """
        Initializes a new instance of the ProxyManager class with an empty proxy list.
        """
        self.proxies: List[Proxy] = []

    @classmethod
    def from_proxies(cls, proxies: List[Proxy]):
        """
        Alternative constructor to initialize ProxyManager with a list of Proxy instances.

        Args:
            proxies (List[Proxy]): A list of Proxy instances.

        Returns:
            ProxyManager: An instance of ProxyManager initialized with the provided proxies.
        """
        manager = cls()
        manager.proxies = proxies.copy()
        logger.info(f"PROXY_MANAGER:: Initialized with {len(proxies)} proxies")
        return manager

    @classmethod
    def from_json(cls, json_data: str):
        """
        Alternative constructor to initialize ProxyManager by processing a JSON string.

        Args:
            json_data (str): A JSON-formatted string containing proxy information.

        Returns:
            ProxyManager: An instance of ProxyManager initialized with proxies from JSON data.
        """
        manager = cls()
        manager.process_proxies(json_data)
        logger.info(f"PROXY_MANAGER:: Initialized from JSON with {len(manager.proxies)} proxies")
        return manager

    @classmethod
    def from_json_file(cls, file_path: str):
        """
        Alternative constructor to initialize ProxyManager by reading and processing a JSON file.

        Args:
            file_path (str): Path to the JSON file containing proxy information.

        Returns:
            ProxyManager: An instance of ProxyManager initialized with proxies from the JSON file.
        """
        try:
            with open(file_path, 'r') as file:
                json_data = file.read()
            logger.info(f"PROXY_MANAGER:: Read JSON data from {file_path}")
            return cls.from_json(json_data)
        except FileNotFoundError:
            logger.error(f"PROXY_MANAGER:: JSON file not found at {file_path}")
            return cls()
        except Exception as e:
            logger.error(f"PROXY_MANAGER:: Error reading JSON file {file_path}: {e}")
            return cls()

    @classmethod
    def from_api(cls, api_endpoint: str, headers: Optional[Dict[str, str]] = None):
        """
        Alternative constructor to initialize ProxyManager by fetching proxies from an external API.

        Args:
            api_endpoint (str): The API endpoint URL to fetch proxy data from.
            headers (Optional[Dict[str, str]]): Optional headers to include in the API request.

        Returns:
            ProxyManager: An instance of ProxyManager initialized with proxies fetched from the API.
        """
        manager = cls()
        try:
            response = requests.get(api_endpoint, headers=headers)
            response.raise_for_status()
            json_data = response.text
            manager.process_proxies(json_data)
            logger.info(f"PROXY_MANAGER:: Initialized from API with {len(manager.proxies)} proxies")
        except requests.exceptions.RequestException as e:
            logger.error(f"PROXY_MANAGER:: Error fetching proxies from API: {e}")
        return manager

    def add_proxy(self, proxy: Proxy) -> None:
        """
        Adds a Proxy instance to the manager's proxy list and logs the action.
        Prevents adding duplicate proxies based on IP and ports.

        Args:
            proxy (Proxy): The Proxy instance to be added.
        """
        if any(existing_proxy.ip == proxy.ip and existing_proxy.ports == proxy.ports for existing_proxy in self.proxies):
            logger.warning(f"PROXY:: proxy {proxy.ip} already exists and was not added")
        else:
            self.proxies.append(proxy)
            logger.info(f"PROXY:: proxy {proxy.ip} added")

    def remove_proxy(self, proxy: Proxy) -> None:
        """
        Removes a specified Proxy instance from the manager's proxy list and logs the action.
        If the proxy is not found, logs a warning.

        Args:
            proxy (Proxy): The Proxy instance to be removed.
        """
        try:
            self.proxies.remove(proxy)
            logger.info(f"PROXY:: proxy {proxy.ip} removed")
        except ValueError:
            logger.warning("PROXY:: proxy not found and cannot be removed")

    def get_active_proxies(self) -> List[Proxy]:
        """
        Retrieves all proxies with a status of 'active' and not expired.

        Returns:
            List[Proxy]: A list of active Proxy instances.
        """
        return [proxy for proxy in self.proxies if proxy.is_active() and not proxy.is_expired()]

    def find_proxy_by_ip(self, ip: str) -> Optional[Proxy]:
        """
        Searches for a Proxy instance in the manager's proxy list by its IP address.

        Args:
            ip (str): The IP address of the proxy to search for.

        Returns:
            Optional[Proxy]: The Proxy instance if found; otherwise, None.
        """
        for proxy in self.proxies:
            if proxy.ip == ip:
                return proxy
        return None

    def remove_proxy_by_ip(self, ip: str) -> None:
        """
        Removes a Proxy instance from the manager's proxy list based on its IP address.
        Logs the action or a warning if the proxy is not found.

        Args:
            ip (str): The IP address of the proxy to be removed.
        """
        proxy = self.find_proxy_by_ip(ip)
        if proxy:
            self.remove_proxy(proxy)
        else:
            logger.warning("PROXY:: proxy not found and cannot be removed")

    def set_status(self, proxy: Proxy, status_str: str) -> bool:
        """
        Sets the status of a specific Proxy instance based on a status string.

        Args:
            proxy (Proxy): The Proxy instance whose status is to be updated.
            status_str (str): The new status as a string (e.g., 'ACTIVE', 'NOT ACTIVE').

        Returns:
            bool: True if the status was successfully updated, False otherwise.
        """
        try:
            proxy_status = ProxyStatus(status_str.upper())
            return proxy.set_status(proxy_status)
        except ValueError:
            logger.error(f"PROXY:: invalid status '{status_str}' provided for proxy {proxy.ip}")
            return False

    def set_status_by_ip(self, ip: str, status_str: str) -> bool:
        """
        Sets the status of a Proxy instance identified by its IP address.

        Args:
            ip (str): The IP address of the proxy whose status is to be updated.
            status_str (str): The new status as a string (e.g., 'ACTIVE', 'NOT ACTIVE').

        Returns:
            bool: True if the status was successfully updated, False otherwise.
        """
        proxy = self.find_proxy_by_ip(ip)
        if proxy:
            return self.set_status(proxy, status_str)
        else:
            logger.warning(f"PROXY:: proxy with IP {ip} not found")
            return False

    def process_proxies(self, json_data: str) -> None:
        """
        Processes a JSON string containing proxy data, creates Proxy instances, and adds them to the manager.
        Logs the outcome of each operation.

        Args:
            json_data (str): A JSON-formatted string containing proxy information.
        """
        try:
            data = json.loads(json_data)
            proxies = data.get("proxies", [])
            if not isinstance(proxies, list):
                logger.error("PROXY:: invalid JSON format: 'proxies' should be a list.")
                return

            for proxy_dict in proxies:
                required_keys = {"ip", "ports", "user", "password", "proxy_address", "exp", "status"}
                if not required_keys.issubset(proxy_dict.keys()):
                    missing = required_keys - proxy_dict.keys()
                    logger.error(f"PROXY:: missing keys {missing} in proxy data: {proxy_dict}")
                    continue

                status_str = proxy_dict["status"].upper()
                try:
                    status = ProxyStatus(status_str)
                except ValueError:
                    status = ProxyStatus.UNDEFINED

                # Proceed to create and add the Proxy instance
                try:
                    proxy = Proxy(
                        ip=proxy_dict["ip"],
                        ports=proxy_dict["ports"],
                        user=proxy_dict["user"],
                        password=proxy_dict["password"],
                        proxy_address=proxy_dict["proxy_address"],
                        exp=proxy_dict["exp"],
                        status=status
                    )
                    self.add_proxy(proxy)
                except KeyError as e:
                    logger.error(f"PROXY:: missing key {e} in proxy data: {proxy_dict}")
                except Exception as e:
                    logger.error(f"PROXY:: error processing proxy data: {e} | Data: {proxy_dict}")

            logger.info(f"PROXY:: successfully added {len(self.proxies)} proxies")

        except json.JSONDecodeError as jde:
            logger.error(f"PROXY:: invalid JSON data provided: {jde}")
        except Exception as e:
            logger.error(f"PROXY:: unexpected error processing proxies JSON: {e}")

    def get_random_proxy(self) -> Optional[Proxy]:
        """
        Retrieves a random active proxy.

        Returns:
            Optional[Proxy]: A random active Proxy instance, or None if no active proxies are available.
        """
        active = self.get_active_proxies()
        if active:
            return random.choice(active)
        logger.warning("PROXY:: no active proxy available")
        return None

    def add_proxy_from_api(self) -> None:
        """
        Placeholder method intended to fetch proxies from an external API.
        Currently not implemented.
        """
        pass

    def __repr__(self) -> str:
        """
        Returns a string representation of the ProxyManager instance, including all managed proxies.

        Returns:
            str: A string representation of the ProxyManager instance.
        """
        return f"ProxyManager(proxies={self.proxies})"


if __name__ == "__main__":
    proxy_list = """
    {
        "proxies": [
            {
                "ip": "127.0.0.1",
                "ports": {
                    "http": 1533,
                    "https": 11533
                },
                "user": "user210707",
                "password": "6qml5v",
                "proxy_address": {
                    "http": "user210707:6qml5v@193.28.183.78:1533",
                    "https": "user210707:6qml5v@193.28.183.78:11533"
                },
                "exp": 1727446376,
                "status": "ACTIVE"
            },
            {
                "ip": "127.0.0.2",
                "ports": {
                    "http": 1533,
                    "https": 11533
                },
                "user": "user210707",
                "password": "6qml5v",
                "proxy_address": {
                    "http": "user210707:6qml5v@193.28.183.78:1533",
                    "https": "user210707:6qml5v@193.28.183.78:11533"
                },
                "exp": 1727446376,
                "status": "ACTIVE"
            }
        ]
    }
    """
    manager = ProxyManager.from_json(proxy_list)
    proxy = manager.get_random_proxy()
    print(proxy)
    if proxy:
        manager.set_status(proxy, 'NOT ACTIVE')
    print(manager.proxies)
