import subprocess
import json

# Define the curl command
curl_command = [
    'curl', '-w', '%{http_code}', '-o', 'response_body.json', '-s',
    'https://api.uzum.uz/api/main/root-categories?eco=false',
    '-H', 'accept: application/json',
    '-H', 'accept-language: ru-RU',
    '-H', 'authorization: Bearer eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE5MjI1NjA5LCJzdWIiOiI1ZjBlMGY4Ny00YTMyLTQ3ZTEtYTMwOC1jZWNlN2M3Y2Y5ZGUiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTkyMjYzMjl9.ab8uGpiduaAus3-5LdITQXG1yZQeCNQNy29yYhR975yWU6SDo0hK-W21I7eDmypLffErl1G5e7ZnpPU-c7_6DQ',
    '-H', 'baggage: sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=eea76a05648f4df2a8c5f13f98b77196,sentry-sample_rate=0.001,sentry-transaction=main,sentry-sampled=false',
    '-H', 'content-type: application/json',
    '-H', 'origin: https://uzum.uz',
    '-H', 'priority: u=1, i',
    '-H', 'referer: https://uzum.uz/',
    '-H', 'sec-ch-ua: "Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    '-H', 'sec-ch-ua-mobile: ?0',
    '-H', 'sec-ch-ua-platform: "macOS"',
    '-H', 'sec-fetch-dest: empty',
    '-H', 'sec-fetch-mode: cors',
    '-H', 'sec-fetch-site: same-site',
    '-H', 'sentry-trace: eea76a05648f4df2a8c5f13f98b77196-a48c5ee00d0eee09-0',
    '-H', 'user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    '-H', 'x-iid: d7e47b3b-1ea6-4b34-9362-d9169f1250e7'
]

# Run the curl command and capture the output
result = subprocess.run(curl_command, capture_output=True, text=True)

# Extract the HTTP status code from the output
http_status = result.stdout[-3:]

# Print the HTTP status code
print(f"HTTP Status Code: {http_status}")

# Print any errors
if result.stderr:
    print(f"Error: {result.stderr}")

# Load the response body from the file
with open('response_body.json', 'r', encoding='utf-8') as f:
    response_body = f.read()

# Parse the JSON data
try:
    json_data = json.loads(response_body)
except json.JSONDecodeError:
    print("Error: Failed to decode JSON")
    json_data = {}

# Save the JSON data to a file
with open('response.json', 'w', encoding='utf-8') as json_file:
    json.dump(json_data, json_file, ensure_ascii=False, indent=4)

# Print a message indicating the data was saved
print("Response data saved to response.json")
