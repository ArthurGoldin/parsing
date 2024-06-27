import http.client
import json

# Define the host and the endpoint
host = 'graphql.uzum.uz'
endpoint = '/'

# Define the headers
headers = {
    'Accept': '*/*',
    'Accept-Language': 'ru-RU',
    'apollographql-client-name': 'web-customers',
    'apollographql-client-version': '1.25.2',
    'Authorization': 'Bearer eyJraWQiOiIwcE9oTDBBVXlWSXF1V0w1U29NZTdzcVNhS2FqYzYzV1N5THZYb0ZhWXRNIiwiYWxnIjoiRWREU0EiLCJ0eXAiOiJKV1QifQ.eyJpc3MiOiJVenVtIElEIiwiaWF0IjoxNzE5NDAwNDM0LCJzdWIiOiI1ZjBlMGY4Ny00YTMyLTQ3ZTEtYTMwOC1jZWNlN2M3Y2Y5ZGUiLCJhdWQiOlsidXp1bV9hcHBzIiwibWFya2V0L3dlYiJdLCJldmVudHMiOnt9LCJleHAiOjE3MTk0MDExNTR9.MS8JX07utUIt2rNEVWZeUFlTmHcrrPKhR3Mayk5oD3JrAKSL_FUdOe_DL65iV7BSSTBAK4ikY2FB6VjDqx2zAQ',
    'Baggage': 'sentry-environment=production,sentry-release=uzum-market%401.25.2,sentry-public_key=e1a87daa698047a7ace4c53be14f63e8,sentry-trace_id=dcdef1759da34ae6894f8629c5d59343',
    'Content-Type': 'application/json',
    'Origin': 'https://uzum.uz',
    'Priority': 'u=1, i',
    'Referer': 'https://uzum.uz/',
    'sec-ch-ua': '"Not/A)Brand";v="8", "Chromium";v="126", "Google Chrome";v="126"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'empty',
    'sec-fetch-mode': 'cors',
    'sec-fetch-site': 'same-site',
    'sentry-trace': 'dcdef1759da34ae6894f8629c5d59343-a55aaf4639abcfa1',
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'x-context': 'null',
    'x-iid': 'd7e47b3b-1ea6-4b34-9362-d9169f1250e7'
}

# Define the data
data = {
    "operationName": "getMakeSearch",
    "variables": {
        "queryInput": {
            "categoryId": "10012",
            "showAdultContent": "TRUE",
            "filters": [],
            "sort": "BY_RELEVANCE_DESC",
            "pagination": {
                "offset": 0,
                "limit": 1
            },
            "correctQuery": False,
            "getFastCategories": True,
            "fastCategoriesLimit": 11,
            "fastCategoriesLevelOffset": 1,
            "getPromotionItems": True
        }
    },
    "query": """query getMakeSearch($queryInput: MakeSearchQueryInput!) {
                  makeSearch(query: $queryInput) {
                    id
                    queryId
                    queryText
                    category {
                      ...CategoryShortFragment
                      __typename
                    }
                    categoryTree {
                      category {
                        ...CategoryFragment
                        __typename
                      }
                      total
                      __typename
                    }
                    items {
                      adMarker {
                        marker
                        __typename
                      }
                      catalogCard {
                        __typename
                        ...SkuGroupCardFragment
                      }
                      bidId
                      __typename
                    }
                    facets {
                      ...FacetFragment
                      __typename
                    }
                    total
                    mayHaveAdultContent
                    categoryFullMatch
                    offerCategory {
                      title
                      id
                      __typename
                    }
                    correctedQueryText
                    categoryWasPredicted
                    fastCategories {
                      category {
                        ...FastCategoryFragment
                        __typename
                      }
                      total
                      __typename
                    }
                    permanentLinkSeo {
                      id
                      seoHeader
                      seoMetaTag
                      seoTitle
                      __typename
                    }
                    token
                    __typename
                  }
                }

                fragment FacetFragment on Facet {
                  filter {
                    id
                    title
                    type
                    measurementUnit
                    description
                    __typename
                  }
                  buckets {
                    filterValue {
                      id
                      description
                      image
                      name
                      __typename
                    }
                    total
                    __typename
                  }
                  range {
                    min
                    max
                    __typename
                  }
                  __typename
                }

                fragment CategoryFragment on Category {
                  id
                  icon
                  parent {
                    id
                    __typename
                  }
                  seo {
                    header
                    metaTag
                    __typename
                  }
                  title
                  title_ru
                  title_uz
                  adult
                  __typename
                }

                fragment CategoryShortFragment on Category {
                  id
                  parent {
                    id
                    title
                    title_ru
                    title_uz
                    __typename
                  }
                  title
                  title_ru
                  title_uz
                  __typename
                }

                fragment FastCategoryFragment on Category {
                  id
                  parent {
                    id
                    title
                    __typename
                  }
                  title
                  seo {
                    header
                    metaTag
                    __typename
                  }
                  __typename
                }

                fragment SkuGroupCardFragment on SkuGroupCard {
                  ...DefaultCardFragment
                  photos {
                    key
                    link(trans: PRODUCT_540) {
                      high
                      low
                      __typename
                    }
                    previewLink: link(trans: PRODUCT_240) {
                      high
                      low
                      __typename
                    }
                    __typename
                  }
                  badges {
                    ... on BottomTextBadge {
                      backgroundColor
                      description
                      id
                      link
                      text
                      textColor
                      __typename
                    }
                    ... on UzumInstallmentTitleBadge {
                      backgroundColor
                      text
                      id
                      textColor
                      __typename
                    }
                    __typename
                  }
                  characteristicValues {
                    id
                    value
                    title
                    characteristic {
                      values {
                        id
                        title
                        value
                        __typename
                      }
                      title
                      id
                      __typename
                    }
                    __typename
                  }
                  __typename
                }

                fragment DefaultCardFragment on CatalogCard {
                  adult
                  favorite
                  feedbackQuantity
                  id
                  minFullPrice
                  minSellPrice
                  offer {
                    due
                    icon
                    text
                    textColor
                    __typename
                  }
                  badges {
                    backgroundColor
                    text
                    textColor
                    __typename
                  }
                  ordersQuantity
                  productId
                  rating
                  title
                  __typename
                }"""
}

# Convert data to JSON string
json_data = json.dumps(data)

# Create a connection
conn = http.client.HTTPSConnection(host)

# Send the request
conn.request("POST", endpoint, body=json_data, headers=headers)

# Get the response
response = conn.getresponse()
response_data = response.read()

# Print the response
print("Status:", response.status)
print("Response data:", response_data.decode('utf-8'))

# Close the connection
conn.close()
