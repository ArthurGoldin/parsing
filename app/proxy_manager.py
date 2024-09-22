from typing import List, Dict, Optional
import logging
import logging.config
import json
import requests
import random
from enum import Enum
import time
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
# from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import threading
import atexit

# Configure logging
try:
    logging.config.fileConfig('configs/logging.conf')
    logger = logging.getLogger('proxy_manager')
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger()
    logger.warning(f"Could not load logger.conf: {e}; defining default logger.")

# Initialize the scheduler with a SQLAlchemy job store (optional for persistence)
# from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
# jobstores = {
#     'default': SQLAlchemyJobStore(url='sqlite:///jobs.sqlite')
# }
# scheduler = BackgroundScheduler(jobstores=jobstores)
scheduler = BackgroundScheduler()
scheduler.start()


# def job_listener(event):
#     if event.exception:
#         logger.error(f"The job {event.job_id} failed with exception: {event.exception}")
#     else:
#         logger.debug(f"The job {event.job_id} executed successfully.")


# Register a shutdown hook
atexit.register(lambda: scheduler.shutdown())


class ProxyUnavailableError(Exception):
    """Exception raised when no proxies are available within the specified timeout."""
    pass


class ProxyStatus(Enum):
    """
    Enum representing the possible statuses of a proxy.

    Attributes:
        ACTIVE (str): Indicates the proxy is active.
        EXPIRED (str) = Indicates the proxy is expired
        NOT_ACTIVE (str): Indicates the proxy is not active.
        PAUSED (str): Indicates the proxy is paused temporarily.
        SLEEPING (str): Indicates the proxy is sleeping temporarily.
        UNDEFINED (str): Indicates the proxy status is undefined.
    """
    ACTIVE = 'ACTIVE'
    EXPIRED = 'EXPIRED'
    NOT_ACTIVE = 'NOT ACTIVE'
    PAUSED = 'PAUSED'
    SLEEPING = 'SLEEPING'
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
        logger.warning(f"Invalid status '{value}' for proxy, setting status to UNDEFINED")
        return cls.UNDEFINED


class Proxy:
    """
    Represents a proxy server configuration.
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
        """
        self.ip = ip
        self.ports = ports
        self.user = user
        self.password = password
        self.proxy_address = proxy_address
        self.exp = exp
        self.status = status
        self._status_lock = threading.Lock()  # To handle concurrent status updates
        self._job_id = None  # To keep track of the scheduled job for reverting status

    def is_active(self) -> bool:
        """
        Determines if the proxy is currently active.
        If the proxy is expired, updates the status accordingly

        Returns:
            bool: True if the proxy status is ACTIVE, False otherwise.
        """
        return self.status == ProxyStatus.ACTIVE and not self.is_expired()

    def is_expired(self) -> bool:
        """
        Checks if the proxy has expired based on the current time and updates its status accordingly.

        Returns:
            bool: True if the current time is greater than the expiration time, False otherwise.
        """
        if time.time() > self.exp:
            if self.set_status != ProxyStatus.EXPIRED:
                self.set_status(ProxyStatus.EXPIRED)
            return True
        return False

    def set_status(self, status: ProxyStatus) -> bool:
        """
        Sets the status of the proxy to the specified value if it's a valid ProxyStatus.

        Args:
            status (ProxyStatus): The new status to set for the proxy.

        Returns:
            bool: True if the status was successfully updated, False otherwise.
        """
        with self._status_lock:
            if isinstance(status, ProxyStatus):
                prev_status = self.status
                self.status = status
                logger.debug(f"Status of {self.ip} changed from {prev_status} to {status.value}")
                return True
            logger.error(f"Wrong status value")
            return False

    def set_temporary_status(self, temp_status: ProxyStatus, duration: int, manager_reference) -> bool:
        """
        Sets a temporary status for the proxy for a specified duration using APScheduler.

        Args:
            temp_status (ProxyStatus): The temporary status to set (PAUSED or SLEEPING).
            duration (int): Duration in seconds for which the status should be active.
            manager_reference (ProxyManager): Reference to the ProxyManager to handle status reversion.

        Returns:
            bool: True if the status was successfully set, False otherwise.
        """
        if temp_status not in {ProxyStatus.PAUSED, ProxyStatus.SLEEPING}:
            logger.error(f"Invalid temporary status '{temp_status}'")
            return False

        with self._status_lock:
            # Cancel any existing scheduled job
            if self._job_id:
                try:
                    scheduler.remove_job(self._job_id)
                    logger.debug(f"Existing job {self._job_id} for {self.ip} removed")
                except JobLookupError:
                    logger.warning(f"Job {self._job_id} not found for {self.ip}")
                self._job_id = None

            # Set the temporary status
            self.status = temp_status
            logger.debug(f"Status of {self.ip} set to {temp_status.value} for {duration} seconds")

            # Calculate the run_time as a datetime object
            run_time = datetime.now() + timedelta(seconds=duration)

            # Schedule the status to revert after 'duration' seconds
            job = scheduler.add_job(
                func=manager_reference.revert_proxy_status,
                trigger='date',
                run_date=run_time,  # Correct: datetime object
                args=[self.ip],
                id=f"revert_status_{self.ip}_{int(run_time.timestamp())}"
            )
            self._job_id = job.id
            logger.debug(f"Scheduled job {self._job_id} to revert status of {self.ip}")

            return True

    def revert_status(self):
        """
        Reverts the proxy status back to ACTIVE if not expired.
        """
        with self._status_lock:
            if not self.is_expired():
                self.status = ProxyStatus.ACTIVE
                logger.debug(f"Status of {self.ip} reverted to ACTIVE after timeout")
            else:
                self.set_status(ProxyStatus.EXPIRED)
                logger.debug(f"Status of {self.ip} changed to {self.status.value} as it is expired")
            self._job_id = None  # Clear the job ID since it's executed

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
    Manages a collection of Proxy instances.
    """

    def __init__(self):
        """
        Initializes a new instance of the ProxyManager class with an empty proxy list.
        """
        self.proxies: List[Proxy] = []
        self._manager_lock = threading.Lock()  # To handle concurrent access
        self.proxy_available = threading.Condition()

    @classmethod
    def from_proxies(cls, proxies: List[Proxy]):
        """
        Alternative constructor to initialize ProxyManager with a list of Proxy instances.
        """
        manager = cls()
        manager.proxies = proxies.copy()
        logger.info(f"Initialized with {len(proxies)} proxies")
        return manager

    @classmethod
    def from_json(cls, json_data: str):
        """
        Alternative constructor to initialize ProxyManager by processing a JSON string.
        """
        manager = cls()
        manager.process_proxies(json_data)
        logger.info(f"Initialized from JSON with {len(manager.proxies)} proxies")
        return manager

    @classmethod
    def from_json_file(cls, file_path: str):
        """
        Alternative constructor to initialize ProxyManager by reading and processing a JSON file.
        """
        try:
            with open(file_path, 'r') as file:
                json_data = file.read()
            logger.info(f"Read JSON data from {file_path}")
            return cls.from_json(json_data)
        except FileNotFoundError:
            logger.error(f"JSON file not found at {file_path}")
            return cls()
        except Exception as e:
            logger.error(f"Error reading JSON file {file_path}: {e}")
            return cls()

    @classmethod
    def from_api(cls, api_endpoint: str, headers: Optional[Dict[str, str]] = None):
        """
        Alternative constructor to initialize ProxyManager by fetching proxies from an external API.
        """
        manager = cls()
        try:
            response = requests.get(api_endpoint, headers=headers)
            response.raise_for_status()
            json_data = response.text
            manager.process_proxies(json_data)
            logger.info(f"Initialized from API with {len(manager.proxies)} proxies")
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching proxies from API: {e}")
        return manager

    def add_proxy(self, proxy: Proxy) -> None:
        """
        Adds a Proxy instance to the manager's proxy list and logs the action.
        Prevents adding duplicate proxies based on IP and ports.
        """
        with self._manager_lock:
            if any(existing_proxy.ip == proxy.ip and existing_proxy.ports == proxy.ports for existing_proxy in self.proxies):
                logger.warning(f"Proxy {proxy.ip} already exists and was not added")
            else:
                self.proxies.append(proxy)
                logger.info(f"Proxy {proxy.ip} added")

    def remove_proxy(self, proxy: Proxy) -> None:
        """
        Removes a specified Proxy instance from the manager's proxy list and logs the action.
        If the proxy is not found, logs a warning.
        """
        with self._manager_lock:
            try:
                self.proxies.remove(proxy)
                logger.info(f"Proxy {proxy.ip} removed")
            except ValueError:
                logger.warning("Proxy not found and cannot be removed")

    def get_active_proxies(self) -> List[Proxy]:
        """
        Retrieves all proxies with a status of 'ACTIVE' and not expired.
        """
        with self._manager_lock:
            return [proxy for proxy in self.proxies if proxy.is_active()]

    def find_proxy_by_ip(self, ip: str) -> Optional[Proxy]:
        """
        Searches for a Proxy instance in the manager's proxy list by its IP address.
        """
        with self._manager_lock:
            for proxy in self.proxies:
                if proxy.ip == ip:
                    return proxy
            return None

    def remove_proxy_by_ip(self, ip: str) -> None:
        """
        Removes a Proxy instance from the manager's proxy list based on its IP address.
        """
        proxy = self.find_proxy_by_ip(ip)
        if proxy:
            self.remove_proxy(proxy)
        else:
            logger.warning("Proxy not found and cannot be removed")

    def set_status(self, proxy: Proxy, status_str: str) -> bool:
        """
        Sets the status of a specific Proxy instance based on a status string.
        """
        try:
            proxy_status = ProxyStatus(status_str.upper())
            return proxy.set_status(proxy_status)
        except ValueError:
            logger.error(f"Invalid status '{status_str}' provided for proxy {proxy.ip}")
            return False

    def set_status_by_ip(self, ip: str, status_str: str) -> bool:
        """
        Sets the status of a Proxy instance identified by its IP address.
        """
        proxy = self.find_proxy_by_ip(ip)
        if proxy:
            return self.set_status(proxy, status_str)
        else:
            logger.warning(f"Proxy with IP {ip} not found")
            return False

    def set_temporary_status(self, proxy: Proxy, temp_status: ProxyStatus, duration: int) -> bool:
        """
        Sets a temporary status for a specific proxy.
        """
        if proxy not in self.proxies:
            logger.warning(f"Proxy {proxy.ip} not managed and cannot set temporary status")
            return False
        return proxy.set_temporary_status(temp_status, duration, self)

    def set_temporary_status_by_ip(self, ip: str, temp_status: ProxyStatus, duration: int) -> bool:
        """
        Sets a temporary status for a proxy identified by its IP address.
        """
        proxy = self.find_proxy_by_ip(ip)
        if proxy:
            return self.set_temporary_status(proxy, temp_status, duration)
        else:
            logger.warning(f"Proxy with IP {ip} not found")
            return False

    def pause_proxy(self, ip: str, duration: int) -> bool:
        """
        Pauses a proxy for a specified duration.
        """
        return self.set_temporary_status_by_ip(ip, ProxyStatus.PAUSED, duration)

    def sleep_proxy(self, ip: str, duration: int) -> bool:
        """
        Puts a proxy to sleep for a specified duration.
        """
        return self.set_temporary_status_by_ip(ip, ProxyStatus.SLEEPING, duration)

    def revert_proxy_status(self, ip: str) -> None:
        """
        Callback function to revert a proxy's status to ACTIVE after the timeout.
        This method is intended to be called by APScheduler.
        """
        try:
            proxy = self.find_proxy_by_ip(ip)
            if proxy:
                proxy.revert_status()
                with self.proxy_available:
                    self.proxy_available.notify_all()
            else:
                logger.warning(f"Proxy with IP {ip} not found for status revert")
        except Exception as e:
            logger.error(f"Error reverting status for proxy {ip}: {e}")

    def process_proxies(self, json_data: str) -> None:
        """
        Processes a JSON string containing proxy data, creates Proxy instances, and adds them to the manager.
        """
        try:
            data = json.loads(json_data)
            proxies = data.get("proxies", [])
            if not isinstance(proxies, list):
                logger.error("Invalid JSON format: 'proxies' should be a list.")
                return

            for proxy_dict in proxies:
                required_keys = {"ip", "ports", "user", "password", "proxy_address", "exp", "status"}
                if not required_keys.issubset(proxy_dict.keys()):
                    missing = required_keys - proxy_dict.keys()
                    logger.error(f"Missing keys {missing} in proxy data: {proxy_dict}")
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
                    logger.error(f"Missing key {e} in proxy data: {proxy_dict}")
                except Exception as e:
                    logger.error(f"Error processing proxy data: {e} | Data: {proxy_dict}")

            logger.info(f"Successfully added {len(self.proxies)} proxies")

        except json.JSONDecodeError as jde:
            logger.error(f"Invalid JSON data provided: {jde}")
        except Exception as e:
            logger.error(f"Unexpected error processing proxies JSON: {e}")

    def get_random_proxy(self) -> Optional[Proxy]:
        """
        Retrieves a random active proxy.
        """
        active = self.get_active_proxies()
        if active:
            logger.info(f"Selected active proxy: {active.ip}")
            return random.choice(active)
        logger.warning("No active proxy available")
        return None

    def get_available_proxy(self, timeout: Optional[int] = None) -> Optional[Proxy]:
        """
        Retrieves a random active proxy. If no active proxies are available,
        checks for sleeping proxies and waits until one becomes active.

        Args:
            timeout (Optional[int]): Maximum time in seconds to wait for an active proxy.
                                     If None, waits indefinitely.

        Returns:
            Optional[Proxy]: A Proxy instance with status ACTIVE, or None if timeout is reached.

        Raises:
            ProxyUnavailableError: If no proxy becomes active within the timeout period.
        """
        start_time = time.time()

        while True:
            active_proxies = self.get_active_proxies()

            if active_proxies:
                selected_proxy = random.choice(active_proxies)
                logger.info(f"Selected active proxy: {selected_proxy.ip}")
                return selected_proxy

            # Check for sleeping proxies
            sleeping_proxies = [proxy for proxy in self.proxies if proxy.status == ProxyStatus.SLEEPING]

            if not sleeping_proxies:
                logger.warning("No active or sleeping proxies available.")
                raise ProxyUnavailableError("No active or sleeping proxies available.")

            # Calculate remaining time if timeout is set
            if timeout is not None:
                elapsed_time = time.time() - start_time
                remaining_time = timeout - elapsed_time
                if remaining_time <= 0:
                    logger.error("Timeout reached while waiting for an active proxy.")
                    raise ProxyUnavailableError("Timeout reached while waiting for an active proxy.")

            else:
                remaining_time = None  # Wait indefinitely

            logger.info("No active proxies. Waiting for a sleeping proxy to become active...")

            # Wait using the condition variable
            with self.proxy_available:
                if remaining_time is not None:
                    self.proxy_available.wait(timeout=remaining_time)
                else:
                    self.proxy_available.wait()

    def add_proxy_from_api(self) -> None:
        """
        Placeholder method intended to fetch proxies from an external API.
        Currently not implemented.
        """
        pass

    def __repr__(self) -> str:
        """
        Returns a string representation of the ProxyManager instance, including all managed proxies.
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
                "exp": 1927446376,
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
                "exp": 1927446376,
                "status": "ACTIVE"
            }
        ]
    }
    """
    manager = ProxyManager.from_json(proxy_list)

    # Get a random active proxy
    proxy = manager.get_random_proxy()
    print(f"Selected Proxy: {proxy}")
    print("\n")

    if proxy:
        # Pause the proxy for 10 seconds
        manager.pause_proxy(proxy.ip, duration=2)
        print(f"After pausing: {proxy}")

        # Sleep the proxy for 5 seconds (this will override the previous pause)
        manager.sleep_proxy(proxy.ip, duration=1)
        print(f"After sleeping: {proxy}")

        # Wait to observe the status changes
        print("Waiting for 5 seconds to allow status to revert...")
        time.sleep(5)
        print(f"Final Status: {proxy}")

    # Print all proxies
    # print(manager.proxies)
