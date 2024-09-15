from typing import List, Dict, Optional
import logging
import logging.config
import json

# Configure logging
logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()


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
        status (str): Current status of the proxy (e.g., 'active', 'inactive').
    """

    def __init__(
        self,
        ip: str,
        ports: Dict[str, int],
        user: str,
        password: str,
        proxy_address: Dict[str, str],
        exp: int,
        status: str
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
            status (str): Current status of the proxy (e.g., 'active', 'inactive').
        """
        self.ip = ip
        self.ports = ports
        self.user = user
        self.password = password
        self.proxy_address = proxy_address
        self.exp = exp
        self.status = status

    def __repr__(self):
        """
        Returns a string representation of the Proxy instance, masking the password for security.

        Returns:
            str: A string representation of the Proxy instance.
        """
        return (
            f"Proxy(ip='{self.ip}', ports={self.ports}, user='{self.user}', "
            f"password='****', proxy_address={self.proxy_address}, "
            f"exp={self.exp}, status='{self.status}')"
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

    def add_proxy(self, proxy: Proxy) -> None:
        """
        Adds a Proxy instance to the manager's proxy list and logs the action.

        Args:
            proxy (Proxy): The Proxy instance to be added.
        """
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
        Retrieves all proxies with a status of 'active'.

        Returns:
            List[Proxy]: A list of active Proxy instances.
        """
        return [proxy for proxy in self.proxies if proxy.status.lower() == 'active']

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
                try:
                    proxy = Proxy(
                        ip=proxy_dict["ip"],
                        ports=proxy_dict["ports"],
                        user=proxy_dict["user"],
                        password=proxy_dict["password"],
                        proxy_address=proxy_dict["proxy_address"],
                        exp=proxy_dict["exp"],
                        status=proxy_dict["status"]
                    )
                    self.add_proxy(proxy)  # Use the add_proxy method for consistency
                except KeyError as ke:
                    logger.error(f"PROXY:: missing key in proxy data: {ke} | Data: {proxy_dict}")
                except Exception as e:
                    logger.error(f"PROXY:: error processing proxy data: {e} | Data: {proxy_dict}")

            logger.info(f"PROXY:: successfully added {len(proxies)} proxies")

        except json.JSONDecodeError as jde:
            logger.error(f"PROXY:: invalid JSON data provided: {jde}")
        except Exception as e:
            logger.error(f"PROXY:: unexpected error processing proxies JSON: {e}")

    def get_proxy_from_api(self) -> None:
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
