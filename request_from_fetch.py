import http.client
import json
import zlib
import brotli
from datetime import datetime

from token_manager import TokenManager

token_manager = TokenManager(
    url="https://uzum.uz/ru",
    max_retries=4,
    save_token=False,
    save_cookies=False
)
auth_token = token_manager.get_token_instance()
# Define the host and the endpoint
host = 'api.uzum.uz'
endpoint = '/api/v2/product/868385'

# Define the headers
headers = {
    'authority': 'api.uzum.uz',
    'method': 'GET',
    'path': '/api/v2/product/868385',
    'scheme': 'https',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Accept-Language': 'ru-RU',
    'Authorization': f'Bearer {auth_token}',
    'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.3,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=7045c04a13404cd1b3abb6633c60702f,sentry-sample_rate=0.001,sentry-transaction=product,sentry-sampled=false',
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
    'Sentry-Trace': '7045c04a13404cd1b3abb6633c60702f-b0db85c265fc14ff-0',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'X-Iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7'
}


def decompress_response(response_data, encoding):
    if encoding == 'gzip':
        return zlib.decompress(response_data, zlib.MAX_WBITS | 16)
    elif encoding == 'deflate':
        try:
            return zlib.decompress(response_data)
        except zlib.error:
            return zlib.decompress(response_data, -zlib.MAX_WBITS)
    elif encoding == 'br':
        return brotli.decompress(response_data)
    else:
        return response_data


try:
    # Create a connection
    conn = http.client.HTTPSConnection(host)

    # Send the request
    conn.request("GET", endpoint, headers=headers)

    # Get the response
    response = conn.getresponse()
    response_data = response.read()
    content_encoding = response.getheader('Content-Encoding')

    # Decompress the response data if necessary
    if content_encoding:
        response_data = decompress_response(response_data, content_encoding)

    # Decode the response data
    decoded_data = response_data.decode('utf-8')

    # Print the raw response data for debugging
    print("Status:", response.status)
    # print("Raw response data:", decoded_data)

    # Check if response data is empty
    if not decoded_data:
        raise ValueError("Empty response data")

    # Parse the JSON data
    json_data = json.loads(decoded_data)

    product_id = endpoint.split('/')[-1]

    # Save the JSON data to a file
    with open(f'response_{product_id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json', 'w', encoding='utf-8') as json_file:
        json.dump(json_data, json_file, ensure_ascii=False, indent=4)

    # Close the connection
    conn.close()
except Exception as e:
    print(f"Error: {e}")
finally:
    if conn.sock:
        conn.close()
