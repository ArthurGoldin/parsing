import requests
from bs4 import BeautifulSoup

# URL of the webpage to scrape
url = 'https://api.uzum.uz/api/main/root-categories?eco=false?'

# Define the headers
headers = {
    'authority': 'api.uzum.uz',
    'method': 'GET',
    'path': '/api/main/root-categories?eco=false',
    'scheme': 'https',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Accept-Language': 'ru-RU',
    'Authorization': 'Bearer eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE5MjMzNTA2LCJzdWIiOiI1ZjBlMGY4Ny00YTMyLTQ3ZTEtYTMwOC1jZWNlN2M3Y2Y5ZGUiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTkyMzQyMjZ9.BNRo9VGc2L4PWzx5wzwVs18UtJwVc3GvrOUV3QnCNtwqGhyprESeiJJJnOtgAuXtSJtLXXoCVbTjGrnryHeaAw',
    'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=0309b22ee8c3423ba9515761a7b25b52,sentry-sample_rate=0.001,sentry-transaction=main,sentry-sampled=false',
    'Content-Type': 'application/json',
    'Origin': 'https://uzum.uz',
    'Priority': 'u=1, i',
    'Referer': 'https://uzum.uz/',
    'Sec-Ch-Ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"macOS"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-site',
    'Sentry-Trace': '0309b22ee8c3423ba9515761a7b25b52-9f3f4f9187dd4fcd-0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'X-Iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7'
}
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.102 Safari/537.36',
    'Referer': 'https://uzum.uz/',
}

# Send a GET request to the URL
response = requests.get(url, headers=headers)

# Check if the request was successful (status code 200)
if response.status_code == 200:
    print(response.status_code)
    # Parse the HTML content of the page
    # soup = BeautifulSoup(response.content, 'html.parser')

    # # Find all article titles (assuming they are within <h2> tags with class 'title')
    # titles = soup.find_all('h1')

    # # Extract and print the text of each title
    # for title in titles:
    #     print(title.get_text())
else:
    print(f"Failed to retrieve the webpage. Status code: {
          response.status_code}")
