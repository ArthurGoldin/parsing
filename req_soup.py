import requests
from bs4 import BeautifulSoup

# URL of the webpage to scrape
url = 'https://uzum.uz/ru'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36',
    'Accept-Language': 'ru-RU',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}
# Send a GET request to the URL
response = requests.get(url)

# Check if the request was successful (status code 200)
if response.status_code == 200:
    print(response.status_code)
    # Parse the HTML content of the page
    soup = BeautifulSoup(response.content, 'html.parser')

    # Find all article titles (assuming they are within <h2> tags with class 'title')
    titles = soup.find_all('h1')

    # Extract and print the text of each title
    for title in titles:
        print(title.get_text())
else:
    print(f"Failed to retrieve the webpage. Status code: {
          response.status_code}")
