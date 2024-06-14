from selenium import webdriver
from bs4 import BeautifulSoup
import re
import json

page_url = "https://uzum.uz/ru"

driver = webdriver.Chrome()  # Or another browser driver
driver.get(page_url)

# Wait for JavaScript to load and execute
driver.implicitly_wait(1000)  # Adjust time based on expected delay

# Get page source after JavaScript execution
page_source = driver.page_source

page_source_json = {
    'page_source': page_source
}

# Save the page source to a JSON file
with open('page_source.json', 'w', encoding='utf-8') as file:
    json.dump(page_source_json, file, ensure_ascii=False, indent=4)


# Parse the source with BeautifulSoup
soup = BeautifulSoup(page_source, 'html.parser')
script_texts = soup.find_all('script')
found_token = None

token_patterns = [
    r"var token = '([^']+)'",  # var token = '...'
    r"var authToken = '([^']+)'",  # var authToken = '...'
    r"var accessToken = '([^']+)'",  # var accessToken = '...'
    r"['\"]accessToken['\"]:\s*['\"]([^'\"]+)['\"]",  # "accessToken": "..."
    r"['\"]token['\"]:\s*['\"]([^'\"]+)['\"]"  # "token": "..."
]

for script in script_texts:
    if script.string:
        for pattern in token_patterns:
            match = re.search(pattern, script.string)
            if match:
                found_token = match.group(1)
                break
    if found_token:
        break

driver.quit()

if found_token:
    print("Found token:", found_token)
else:
    print("Token not found in dynamically loaded content.")
