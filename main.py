import requests
import json

# Define the URLs
main_url = 'https://uzum.uz/ru'
graphql_url = 'https://graphql.uzum.uz/'
token_url = 'https://id.uzum.uz/api/auth/token'

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.93 Safari/537.36',
    'Accept-Language': 'ru-RU',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
}

# Create a session to maintain cookies
session = requests.Session()

# Send a GET request to the main URL to initiate the session
response = session.get(main_url, headers=headers)  # , headers=token_headers)

# Check if the request was successful
auth_token = None
if response.status_code == 200:

    for cookie in session.cookies:
        print("Found token in cookies:", cookie.value)

    cookies = session.cookies.get_dict()
    headers = response.headers

    print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
    # print(cookies)
    print('!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
    # print(headers)

else:
    print("Failed to load the page. Status code:", response.status_code)
    print(response.content)

# Example of how to use the token to make a request to the GraphQL endpoint
if auth_token:
    graphql_query = {
        "query": "{ your_graphql_query_here }"
    }

    # Set the authorization header for the GraphQL request
    graphql_headers = {
        'Authorization': f'Bearer {auth_token}'
    }

    # Send the request to the GraphQL endpoint
    graphql_response = session.post(
        graphql_url, json=graphql_query, headers=graphql_headers)

    # Check if the GraphQL request was successful
    if graphql_response.status_code == 200:
        print("GraphQL Response:", graphql_response.json())
    else:
        print("Failed to fetch GraphQL data. Status code:",
              graphql_response.status_code)
else:
    print("Authorization token is not available. Cannot proceed with GraphQL request.")

print(headers)
headers["Connection"] = "1"
print(headers)


def conditional_yield(n):
    for i in range(n):
        if i % 2 == 0:
            yield i, i ** 2  # Yielding a tuple of (number, number squared)


# Calling the generator function
for number, square in conditional_yield(10):
    print(f"Number: {number}, Square: {square}")

n = 10
pre_allocated_list = [None] * n
print(pre_allocated_list)
print(len(pre_allocated_list))
