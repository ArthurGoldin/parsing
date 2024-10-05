from typing import List, Dict, Optional, Tuple
import logging
import logging.config
import json
import requests
import random
import time
import threading
import atexit
import ipaddress
import socket
import uuid
import http.client
import base64
from enum import Enum
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.base import JobLookupError
# from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

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


# scheduler = BackgroundScheduler()
# try:
#     scheduler.start()
#     logger.info("Scheduler started successfully.")
# except Exception as e:
#     logger.error(f"Failed to start scheduler: {e}")
#     raise

# # Register a shutdown hook
# def shutdown_scheduler():
#     try:
#         scheduler.shutdown(wait=False)
#         logger.info("Scheduler shut down successfully via atexit.")
#     except Exception as e:
#         logger.error(f"Error shutting down scheduler: {e}")

# atexit.register(shutdown_scheduler)


class ProxyUnavailableError(Exception):
    """Exception raised when no proxies are available within the specified timeout."""

    def __init__(self, message: str = "No proxies available within the specified timeout.", timeout: Optional[int] = None, available_proxies: Optional[List['Proxy']] = None):
        """
        Initializes the ProxyUnavailableError.

        Args:
            message (str): Explanation of the error.
            timeout (Optional[int]): The timeout duration in seconds.
            available_proxies (Optional[List[Proxy]]): List of proxies that were available before timeout.
        """
        super().__init__(message)
        self.timeout = timeout
        self.available_proxies = available_proxies or []

    def __str__(self):
        base_message = super().__str__()
        timeout_info = f" Timeout: {self.timeout} seconds." if self.timeout is not None else ""
        proxy_info = f" Available Proxies: {[proxy.ip for proxy in self.available_proxies]}" if self.available_proxies else ""
        return f"{base_message}{timeout_info}{proxy_info}"


class ProxyStatus(Enum):
    """
    Enum representing the possible statuses of a proxy.

    Attributes:
        ACTIVE (str): Indicates the proxy is active.
        BLOCKED (str): Indicates the proxy was blocked by a server (host)
        EXPIRED (str) = Indicates the proxy is expired
        NOT_ACTIVE (str): Indicates the proxy is not active.
        PAUSED (str): Indicates the proxy is paused temporarily.
        SLEEPING (str): Indicates the proxy is sleeping temporarily.
        UNDEFINED (str): Indicates the proxy status is undefined.
    """
    ACTIVE = 'ACTIVE'
    BLOCKED = 'BLOCKED'
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
        status: 'ProxyStatus',  # Assuming ProxyStatus is an enum or similar class
        scheduler: BackgroundScheduler  # Reference to the ProxyManager's scheduler
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
        self._status_lock = threading.Lock()  # To handle concurrent status updates
        self._status = status  # Use _status as a backing attribute
        self._job_id = None  # To keep track of the scheduled job for reverting status
        self.scheduler = scheduler  # Reference to the ProxyManager's scheduler

    @property
    def status(self) -> 'ProxyStatus':
        """
        Thread-safe getter for the proxy's status.
        """
        with self._status_lock:
            logger.debug(f"Reading status of {self.ip}: {self._status.value}")
            return self._status

    @status.setter
    def status(self, new_status: 'ProxyStatus'):
        """
        Thread-safe setter for the proxy's status.
        """
        with self._status_lock:
            logger.debug(f"Changing status of {self.ip} from {self._status.value} to {new_status.value}")
            self._status = new_status

    def is_active(self) -> bool:
        """
        Determines if the proxy is currently active.
        If the proxy is expired, updates the status accordingly.

        Returns:
            bool: True if the proxy status is ACTIVE, False otherwise.
        """
        with self._status_lock:
            return self._status == ProxyStatus.ACTIVE and not self._check_expired()

    def _check_expired(self) -> bool:
        """
        Internal method to check expiration without acquiring the lock.
        """
        if time.time() > self.exp:
            if self._status != ProxyStatus.EXPIRED:
                self._status = ProxyStatus.EXPIRED
            return True
        return False

    def is_expired(self) -> bool:
        """
        Checks if the proxy has expired based on the current time and updates its status accordingly.

        Returns:
            bool: True if the current time is greater than the expiration time, False otherwise.
        """
        if time.time() > self.exp:
            if self.status != ProxyStatus.EXPIRED:  # Use property to ensure the setter is triggered
                self.status = ProxyStatus.EXPIRED   # This will call the setter
            return True
        return False

    # def get_status(self) -> ProxyStatus:
    #     """
    #     Returns a status of the proxy
    #     """
    #     with self._status_lock:

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
                self._status = status
                logger.debug(f"Status of {self.ip} changed from {prev_status} to {status.value}")
                return True
            logger.error(f"Wrong status value {status}")
            return False

    def set_temporary_status(self, temp_status: ProxyStatus, duration: float, manager_reference) -> bool:
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

        # with self._status_lock:
        # Cancel any existing scheduled job
        if self._job_id:
            try:
                self.scheduler.remove_job(self._job_id)
                logger.debug(f"Existing job {self._job_id} for {self.ip} removed")
            except JobLookupError:
                logger.warning(f"Job {self._job_id} not found for {self.ip}")
            self._job_id = None

        # Set the temporary status
        self.status = temp_status  # Directly set the backing attribute, avoiding recursion
        logger.debug(f"Status of {self.ip} set to {temp_status.value} for {duration} seconds")

        # Calculate the run_time as a datetime object
        run_time = datetime.now(timezone.utc) + timedelta(seconds=duration)

        try:
            # Schedule the status to revert after 'duration' seconds
            job = self.scheduler.add_job(
                func=manager_reference.revert_proxy_status,
                trigger='date',
                run_date=run_time,
                args=[self.ip],
                id=f"revert_status_{self.ip}_{str(uuid.uuid4())[0:4]}"
            )
            self._job_id = job.id
            logger.debug(f"Scheduled job {self._job_id} to revert status of {self.ip}")
        except Exception as e:
            logger.error(f"Failed to schedule job to revert status for {self.ip}: {e}")
            return False

        return True

    def revert_status(self):
        """
        Reverts the proxy status back to ACTIVE if not expired.
        """
        # with self._status_lock:
        if not self._check_expired():
            self.status = ProxyStatus.ACTIVE
            logger.debug(f"Status of {self.ip} reverted to ACTIVE after timeout")
        else:
            self.status = ProxyStatus.EXPIRED
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

    def __init__(self, check_exp_interval: int = 100):
        """
        Initializes a new instance of the ProxyManager class with an empty proxy list.
        """
        self.proxies: List[Proxy] = []
        self._manager_lock = threading.Lock()  # To handle concurrent access
        self.proxy_available = threading.Condition(self._manager_lock)

        self.scheduler = BackgroundScheduler(timezone=timezone.utc)
        try:
            self.scheduler.start()
            logger.info("Scheduler started successfully.")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
            raise

        # Schedule periodic expiration checks every 10 minutes
        self.scheduler.add_job(
            self.check_expired_proxies,
            trigger='interval',
            minutes=check_exp_interval,
            id=f"check_expired_proxies_{uuid.uuid4()}"
        )
        atexit.register(lambda: self.shutdown_scheduler("atexit"))

    def shutdown_scheduler(self, msg: str = "default"):
        """
        Shuts down the scheduler associated with this ProxyManager instance.
        """
        try:
            self.scheduler.shutdown(wait=False)
            logger.info(f"Scheduler shut down successfully via {msg}.")
        except Exception as e:
            if str(e).lower() != "scheduler is not running":
                logger.error(f"Error shutting down scheduler: {e}")
            else:
                logger.debug(f"Can't shut down scheduler: {e}")

    def __enter__(self):
        """
        Enter the runtime context related to this object.

        Returns:
            ProxyManager: The ProxyManager instance itself.
        """
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit the runtime context and shut down the scheduler.

        Args:
            exc_type: The exception type.
            exc_val: The exception value.
            exc_tb: The traceback.
        """
        self.shutdown_scheduler()

    def monitor_jobs(self):
        """
        Monitors scheduled jobs and logs their status.
        """
        jobs = self.scheduler.get_jobs()
        for job in jobs:
            logger.debug(f"Job ID: {job.id}, Next Run Time: {job.next_run_time}")

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
    def from_json_file(cls, file_path: str = "data/proxy/proxy.json"):
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

    @staticmethod
    def validate_proxy_address(address: str) -> bool:
        """
        Validates the format and resolves the proxy address string.

        Args:
            address (str): The proxy address string to validate.

        Returns:
            bool: True if the address is valid and resolvable, False otherwise.
        """
        # Split the address into user:pass@host:port
        try:
            user_pass, host_port = address.split('@')
            host, port = host_port.rsplit(':', 1)

            # Validate port
            port = int(port)
            if not (1 <= port <= 65535):
                return False

            # Validate host by attempting to resolve it
            try:
                socket.getaddrinfo(host, port)
            except socket.error:
                return False

            # Optional: Further validate user:pass if needed
            if not user_pass or ':' not in user_pass:
                return False

            return True
        except (ValueError, socket.error):
            return False

    @staticmethod
    def validate_proxy_data(proxy_dict: Dict) -> bool:
        """
        Validates the proxy data dictionary to ensure all required fields are present and correctly formatted.

        Args:
            proxy_dict (Dict): A dictionary containing proxy data.

        Returns:
            bool: True if the proxy data is valid, False otherwise.
        """
        required_keys = {"ip", "ports", "user", "password", "proxy_address", "exp", "status"}

        # Check for missing keys
        if not required_keys.issubset(proxy_dict.keys()):
            missing = required_keys - proxy_dict.keys()
            logger.error(f"Validation Error: Missing keys {missing} in proxy data: {proxy_dict}")
            return False

        # Validate IP address
        try:
            ipaddress.ip_address(proxy_dict["ip"])
        except ValueError:
            logger.error(f"Validation Error: Invalid IP address '{proxy_dict['ip']}' in proxy data: {proxy_dict}")
            return False

        # Validate ports
        ports = proxy_dict["ports"]
        if not isinstance(ports, dict):
            logger.error(f"Validation Error: 'ports' should be a dictionary in proxy data: {proxy_dict}")
            return False
        for protocol in ["http", "https"]:
            if protocol not in ports:
                logger.error(f"Validation Error: Missing '{protocol}' port in proxy data: {proxy_dict}")
                return False
            port = ports[protocol]
            if not isinstance(port, int) or not (1 <= port <= 65535):
                logger.error(f"Validation Error: Invalid port '{port}' for protocol '{protocol}' in proxy data: {proxy_dict}")
                return False

        # Validate user and password
        if not isinstance(proxy_dict["user"], str) or not proxy_dict["user"]:
            logger.error(f"Validation Error: Invalid or empty 'user' in proxy data: {proxy_dict}")
            return False
        if not isinstance(proxy_dict["password"], str) or not proxy_dict["password"]:
            logger.error(f"Validation Error: Invalid or empty 'password' in proxy data: {proxy_dict}")
            return False

        # Validate proxy_address
        proxy_address = proxy_dict["proxy_address"]
        if not isinstance(proxy_address, dict):
            logger.error(f"Validation Error: 'proxy_address' should be a dictionary in proxy data: {proxy_dict}")
            return False
        for protocol in ["http", "https"]:
            if protocol not in proxy_address:
                logger.error(f"Validation Error: Missing '{protocol}' proxy_address in proxy data: {proxy_dict}")
                return False
            address = proxy_address[protocol]
            if not isinstance(address, str) or not ProxyManager.validate_proxy_address(address):
                logger.error(f"Validation Error: Invalid proxy_address '{address}' for protocol '{protocol}' in proxy data: {proxy_dict}")
                return False

        # Validate expiration time
        exp = proxy_dict["exp"]
        if not isinstance(exp, (int, float)) or exp <= time.time():
            logger.error(f"Validation Error: Invalid or past 'exp' timestamp '{exp}' in proxy data: {proxy_dict}")
            return False

        # Validate status
        status_str = proxy_dict["status"].upper()
        if status_str not in ProxyStatus.__members__:
            logger.warning(f"Validation Warning: Unknown status '{status_str}' in proxy data: {proxy_dict}. Setting to UNDEFINED.")
            # The ProxyStatus Enum will handle this by setting it to UNDEFINED

        # All validations passed
        return True

    @staticmethod
    def test_proxy(proxy_addr: Dict[str, str]) -> bool:
        """
            Temporary function for custom proxy checking
        """
        try:
            response = requests.get("https://ipinfo.io", proxies=proxy_addr, timeout=5)
            logger.debug("Proxy is valid")
            # logger.info(response.json())
            return True
        except requests.exceptions.ProxyError:
            logger.error("Proxy connection failed.")
            return False

    def check_expired_proxies(self):
        with self._manager_lock:
            for proxy in self.proxies:
                if proxy.is_expired():
                    logger.info(f"Proxy {proxy.ip} has expired and is now set to EXPIRED.")
                    self.proxy_available.notify_all()

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

    def get_sleeping_proxies(self) -> List[Proxy]:
        """
        Retrieves all proxies with a status of 'SLEEPING' and not expired.
        """
        with self._manager_lock:
            return [proxy for proxy in self.proxies if proxy.status == ProxyStatus.SLEEPING]

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
        try:
            proxy_status = ProxyStatus(status_str.upper())
            result = proxy.set_status(proxy_status)
            if result and proxy_status == ProxyStatus.ACTIVE:
                with self.proxy_available:
                    self.proxy_available.notify_all()
            return result
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

    def set_temporary_status(self, proxy: Proxy, temp_status: ProxyStatus, duration: float) -> bool:
        """
        Sets a temporary status for a specific proxy.
        """
        if proxy not in self.proxies:
            logger.warning(f"Proxy {proxy.ip} not managed and cannot set temporary status")
            return False
        return proxy.set_temporary_status(temp_status, duration, self)

    def set_temporary_status_by_ip(self, ip: str, temp_status: ProxyStatus, duration: float) -> bool:
        """
        Sets a temporary status for a proxy identified by its IP address.
        """
        proxy = self.find_proxy_by_ip(ip)
        if proxy:
            return self.set_temporary_status(proxy, temp_status, duration)
        else:
            logger.warning(f"Proxy with IP {ip} not found")
            return False

    def pause_proxy(self, ip: str, duration: float) -> bool:
        """
        Pauses a proxy for a specified duration.
        """
        return self.set_temporary_status_by_ip(ip, ProxyStatus.PAUSED, duration)

    def sleep_proxy(self, ip: str, duration: float) -> bool:
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
        Processes a JSON string containing proxy data, validates each proxy, creates Proxy instances,
        and adds them to the manager.
        """
        try:
            data = json.loads(json_data)
            proxies = data.get("proxies", [])
            if not isinstance(proxies, list):
                logger.error("Invalid JSON format: 'proxies' should be a list.")
                return

            invalid_proxies = []
            for proxy_dict in proxies:
                if self.validate_proxy_data(proxy_dict):
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
                            status=status,
                            scheduler=self.scheduler
                        )
                        self.add_proxy(proxy)
                    except KeyError as e:
                        logger.error(f"Missing key {e} in proxy data: {proxy_dict}")
                        invalid_proxies.append(proxy_dict)
                    except Exception as e:
                        logger.error(f"Error processing proxy data: {e} | Data: {proxy_dict}")
                        invalid_proxies.append(proxy_dict)
                else:
                    # Proxy data is invalid; already logged within validate_proxy_data
                    invalid_proxies.append(proxy_dict)

            logger.info(f"Successfully added {len(self.proxies)} proxies")
            if invalid_proxies:
                logger.warning(f"Skipped {len(invalid_proxies)} invalid proxies.")
        except json.JSONDecodeError as jde:
            logger.error(f"Invalid JSON data provided: {jde}")
        except Exception as e:
            logger.error(f"Unexpected error processing proxies JSON: {e}")

    def get_random_proxy(self) -> Optional[Proxy]:
        """
        Retrieves a random active proxy.

        Returns:
            Optional[Proxy]: A Proxy instance with status ACTIVE, or None if no active proxies are available.
        """
        active_proxies = self.get_active_proxies()
        if active_proxies:
            selected_proxy = random.choice(active_proxies)
            logger.debug(f"Selected active proxy: {selected_proxy.ip}")
            return selected_proxy
        else:
            logger.warning("No active proxies available!")
            return None

    def get_available_proxy(self, timeout: Optional[float] = None) -> Optional[Proxy]:
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
                logger.debug(f"Selected active proxy: {selected_proxy.ip}")
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
                    raise ProxyUnavailableError(
                        message="Timeout reached while waiting for an active proxy.",
                        timeout=timeout,
                        available_proxies=self.proxies
                    )

            else:
                remaining_time = 3600  # wait at most 100 seconds

            logger.info("No active proxies. Waiting for a sleeping proxy to become active...")

            # Wait using the condition variable
            with self.proxy_available:
                if remaining_time is not None:
                    self.proxy_available.wait(timeout=remaining_time)
                else:
                    self.proxy_available.wait()

    def make_connection(self, host: Optional[str], timeout: Optional[float] = 10) -> Tuple[http.client.HTTPSConnection, str]:
        """
        Make a connection to an available proxy and tunnel to the host
        Args:
            host (Optional[str]): The host the tunneling is crated to
            timeout (Optional[int]): Maximum time in seconds to wait for an active proxy.
                                     If None, waits indefinitely.
        Returns:
            http.client.HTTPSConnection: the http.client connection
            str: An ip of the proxy
        """

        proxy = self.get_available_proxy(timeout=timeout)
        if proxy is not None:
            # Encode credentials for Proxy-Authorization header
            credentials = f"{proxy.user}:{proxy.password}"
            encoded_credentials = base64.b64encode(credentials.encode('utf-8')).decode('utf-8')

            try:
                # Set up a connection to the proxy
                conn = http.client.HTTPSConnection(proxy.ip, proxy.ports['https'])
                if host:
                    # Set up a tunnel to the target host using the CONNECT method
                    conn.set_tunnel(host, headers={'Proxy-Authorization': f'Basic {encoded_credentials}'})
                    logger.debug(f"Connection to {host} established through proxy {proxy.ip}:{proxy.ports['https']}")
                else:
                    logger.debug(f"Connection to proxy established {proxy.ip}:{proxy.ports['https']}")

                return conn, proxy.ip
            except Exception as e:
                logger.error(f"Proxy connection error: {e}")
        else:
            raise ProxyUnavailableError("Proxy not available")

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


def convert_to_unix_timestamp(date_str: str) -> float:
    # Remove the "(UTC+3)" part and extract the UTC offset
    date_part, time_part, tz_part = date_str.split(" ")
    utc_offset_hours = int(tz_part[4:-1])  # Extract "+3" from "(UTC+3)" and convert to integer

    # Parse the date and time using strptime
    dt = datetime.strptime(f"{date_part} {time_part}", "%d.%m.%Y %H:%M")

    # Adjust the time for the timezone offset (UTC+3 in this case)
    dt -= timedelta(hours=utc_offset_hours)

    # Convert to a Unix timestamp
    unix_timestamp = dt.timestamp().__int__()

    return unix_timestamp


if __name__ == "__main__":
    proxy_list = """
    {
        "proxies": [
            {
                "ip": "193.28.183.161",
                "ports": {
                    "http": 6176,
                    "https": 6176
                },
                "user": "user210707",
                "password": "6qml5v",
                "proxy_address": {
                    "http": "user210707:6qml5v@193.28.183.161:6176",
                    "https": "user210707:6qml5v@193.28.183.161:6176"
                },
                "exp": 1729150920,
                "status": "ACTIVE"
            },
            {
                "ip": "93.28.183.102",
                "ports": {
                    "http": 6176,
                    "https": 6176
                },
                "user": "user210707",
                "password": "6qml5v",
                "proxy_address": {
                    "http": "user210707:6qml5v@193.28.183.102:6176",
                    "https": "user210707:6qml5v@193.28.183.102:6176"
                },
                "exp": 1729150920,
                "status": "ACTIVE"
            }
        ]
    }
    """
    # manager = ProxyManager.from_json(proxy_list)
    manager = ProxyManager.from_json_file('data/proxy/proxy.json')
    manager1 = ProxyManager.from_json_file('data/proxy/proxy.json')

    for i in range(4):
        # Get a random active proxy
        proxy = manager.get_available_proxy()
        # print(f"Selected Proxy: {proxy}")

        if proxy:
            # Pause the proxy for 10 seconds
            # manager.pause_proxy(proxy.ip, duration=2)
            # print(f"After pausing: {proxy}")

            # Sleep the proxy for 5 seconds (this will override the previous pause)
            print(f"setting proxy {proxy.ip} for a sleep")
            manager.sleep_proxy(proxy.ip, duration=2)
            # print(f"After sleeping: {proxy}")

            # Wait to observe the status changes
            # print("Waiting for 5 seconds to allow status to revert...")
            # time.sleep(5)
            # print(f"Final Status: {proxy}")
    time.sleep(5)
    print(f"Number of active proxies: {len(manager.get_active_proxies())}")

    manager.shutdown_scheduler("checking")
    # Print all proxies
    # print(manager.proxies)
