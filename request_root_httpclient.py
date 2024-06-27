import http.client
import json
import zlib
import brotli

# Define the host and the endpoint
host = 'api.uzum.uz'
endpoint = '/api/main/root-categories?eco=false'

# Define the headers
headers = {
    'authority': 'api.uzum.uz',
    'Accept': 'application/json',
    'Accept-Encoding': 'gzip, deflate, br, zstd',
    'Accept-Language': 'ru-RU',
    'Authorization': 'Bearer ',  # Include the actual token if needed
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
}


def decompress_http_response(response_data, encoding):
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
        response_data = decompress_http_response(
            response_data, content_encoding)

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

    # Save the JSON data to a file
    with open('response1.json', 'w', encoding='utf-8') as json_file:
        json.dump(json_data, json_file, ensure_ascii=False, indent=4)

except Exception as e:
    print(f"Error: {e}")
finally:
    # Ensure the connection is closed
    conn.close()
