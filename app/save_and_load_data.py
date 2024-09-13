from typing import List, Any, Dict, Union
from typing import List, Any
from datetime import datetime
from typing import List, Any, Dict
import os
import logging
import logging.config
import json
import csv
import glob

logging.config.fileConfig('configs/logging.conf')
logger = logging.getLogger()


# def save_to_file(file: List[Any], file_name: str, sub_dir: str = "", file_type: str = "", add_date_time: bool = False, data_dir: str = 'data', separate_folder: bool = True) -> None:
#     """
#     Save the given data to a CSV/JSON file.

#     Args:
#         file (List[Any]): Data to be saved.
#         file_name (str): Name of the file.
#         sub_dir (str, optional): Sub-directory within the data directory.
#         add_date_time (bool, optional): Whether to append the current datetime to the file name.
#     """
#     dir_path = f"{data_dir}/{sub_dir}/{datetime.now().strftime("%d%m%Y") if separate_folder else ""}"
#     if not os.path.exists(dir_path):
#         os.makedirs(dir_path)
#     orig_file_name = file_name
#     if add_date_time:
#         file_name = f'{file_name}_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

#     if file_type == "CSV" or file_type == "csv" or file_type == "":
#         with open(f'{dir_path}/{file_name}.csv', 'w', newline='') as write_file:
#             writer = csv.writer(write_file)
#             writer.writerow(file['data'] if 'data' in file else file)
#             logger.info(f"{orig_file_name}.csv saved to {dir_path}")
#     if file_type == "JSON" or file_type == "json" or file_type == "":
#         with open(f"{dir_path}/{file_name}.json", 'w', encoding='utf-8') as write_file:
#             json.dump(file, write_file, ensure_ascii=False, indent=4)
#             logger.info(f"{orig_file_name}.json saved to {dir_path}")


def save_to_file(file: Union[List[Any], Dict[str, Any]],
                 file_name: str,
                 sub_dir: str = "",
                 data_dir: str = 'data',
                 file_type: str = "",
                 add_date_time: bool = True,
                 separate_folder: bool = False,
                 override_file: bool = True) -> None:
    """
    Save the given data to a CSV/JSON file. If the file exists, the data will be appended by default or overridden based on the override_file flag.

    Args:
        file (Union[List[Any], Dict[str, Any]]): Data to be saved. For JSON files, it can be a dictionary with a nested structure or a list of dictionaries. 
        file_name (str): Name of the file. The extension is automatically determined by the file_type argument.
        sub_dir (str, optional): Sub-directory within the data directory where the file will be saved. Defaults to "" (root data directory).
        file_type (str, optional): Type of the file to be saved. Accepts "csv" or "json". If not specified, CSV is assumed.
        add_date_time (bool, optional): Whether to append the current datetime to the file name. Defaults to False.
        data_dir (str, optional): Root data directory where files will be saved. Defaults to 'data'.
        separate_folder (bool, optional): Whether to create a separate folder for each day using the current date. Defaults to True.
        override_file (bool, optional): Whether to override the file if it exists. Defaults to False, meaning data will be appended.

    Returns:
        None: The function saves the data to the specified file and does not return anything.
    """
    dir_path = f"{data_dir}/{sub_dir}/{datetime.now().strftime("%Y%m%d") if separate_folder else ''}"
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    orig_file_name = file_name
    if add_date_time:
        file_name = f'{file_name}_{datetime.now().strftime("%Y%m%d")}'

    if file_type.lower() == "csv":  # or file_type == "":
        file_path_csv = f'{dir_path}/{file_name}.csv'
        write_method = 'w' if override_file else 'a'
        with open(file_path_csv, write_method, newline='') as write_file:
            writer = csv.writer(write_file)
            writer.writerow(file['data'])
            logger.info(f"{orig_file_name}.csv saved to {dir_path}")

    if file_type.lower() == "json" or file_type == "":
        file_path_json = f"{dir_path}/{file_name}.json"
        if os.path.exists(file_path_json) and not override_file:
            with open(file_path_json, 'r+', encoding='utf-8') as write_file:
                existing_data = json.load(write_file)
                if isinstance(existing_data, dict) and 'data' in existing_data:
                    if isinstance(file, dict) and 'data' in file:
                        existing_data['data'].extend(file['data'])
                    else:
                        existing_data['data'].extend(file)
                else:
                    if isinstance(existing_data, list):
                        existing_data.extend(file)
                    else:
                        existing_data.update(file)
                write_file.seek(0)
                json.dump(existing_data, write_file, ensure_ascii=False, indent=4)
        else:
            with open(file_path_json, 'w', encoding='utf-8') as write_file:
                json.dump(file, write_file, ensure_ascii=False, indent=4)
        logger.info(f"{orig_file_name}.json saved to {dir_path}")


def save_html_to_file(html: str, filename: str) -> None:
    """
    Save the HTML content to a file.

    Args:
        html (str): The HTML content to be saved.
        filename (str): The name of the file.

    Returns:
        None
    """
    with open(f"data/{filename}", 'w', encoding='utf-8') as file:
        file.write(html)
        logger.info(f"Saved {filename} to data dir.")


def load_last_saved_csv(directory: str = "data", file_name: str = "") -> List[int]:
    """
    Load the last saved CSV file from the specified directory.

    Args:
        directory (str): The directory containing the CSV files.
        name (str): The base name of the CSV files.

    Returns:
        List[int]: List of integers read from the CSV file.
    """
    try:
        if file_name.endswith('.csv'):
            logger.info(f'Loading {file_name} from {directory}')
            latest_file_path = f"{directory}/{file_name}"
        else:
            list_of_files = glob.glob(os.path.join(
                directory, f'{file_name}*.csv'))
            if not list_of_files:
                raise FileNotFoundError(f"No CSV files found in the {directory}.")
            latest_file_path = max(list_of_files, key=os.path.getctime)

            logger.info(f'Loading {latest_file_path}')

        with open(latest_file_path, newline='') as csvfile:
            reader = csv.reader(csvfile)
            for row in reader:
                int_list = [int(item) for item in row]
        return int_list
    except FileNotFoundError as e:
        logging.error(f'Failed to load the last saved CSV file: {e}')
        return None
    except csv.Error:
        logging.error(f"Error decoding CSV from the file {latest_file_path}.")
        return None


def load_last_saved_json(directory: str = "data", file_name: str = "") -> List:
    """
    Load the last saved JSON file from the specified directory.

    Args:
        directory (str): The directory containing the JSON files.
        name (str): The base name of the JSON files.

    Returns:
        List[int]: List from json
    """
    try:
        if file_name.endswith('.json'):
            logger.info(f'Loading {file_name} from {directory}')
            latest_file_path = f"{directory}/{file_name}"
        else:
            list_of_files = glob.glob(os.path.join(
                directory, f'{file_name}*.json'))
            if not list_of_files:
                raise FileNotFoundError(f"No JSON files found in directory {directory}.")
            latest_file_path = max(list_of_files, key=os.path.getctime)

            logger.info(f'Loading {latest_file_path}')

        with open(latest_file_path, 'r', encoding='utf-8') as file:
            category_dict = json.load(file)
        logger.info(f"Loaded data from {latest_file_path}.")
        return category_dict
    except FileNotFoundError as e:
        logger.error(f"File not found: {e}")
        return None
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from the file {latest_file_path}.")
        return None


def load_json(file_path: str) -> Dict[str, Any]:
    """
    Load JSON file.

    Args:
        file_path (str): Path to the JSON file.

    Returns:
        Dict[str, Any]: The JSON data.
    """
    with open(file_path, 'r', encoding='utf-8') as file:
        return json.load(file)


def load_last_saved_root_categories(directory: str = "data/root_categories") -> Dict[str, Any]:
    """
    Load the last saved root categories JSON file from the specified directory.

    Args:
        directory (str): The directory containing the JSON files.

    Returns:
        Dict[str, Any]: The root categories data.
    """
    try:
        list_of_files = glob.glob(os.path.join(
            directory, 'root_categories_*.json'))
        if not list_of_files:
            raise FileNotFoundError(
                "No root_categories files found in the directory.")

        latest_file = max(list_of_files, key=os.path.getctime)

        with open(latest_file, 'r', encoding='utf-8') as file:
            root_categories = json.load(file)

        logging.info(f'Loaded root-categories from {latest_file}')
        return root_categories

    except Exception as e:
        logging.error(f'Failed to load the last saved root-categories: {e}')
        return None
