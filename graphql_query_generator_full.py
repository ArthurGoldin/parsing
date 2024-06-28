import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


def set_query_variables(data: dict, category_id: str, offset: int = 0, limit: int = 1, showAdultContent: str = "TRUE",
                        filters: list = None, sort: str = "BY_RELEVANCE_DESC", correctQuery: bool = False,
                        getFastCategories: bool = True, fastCategoriesLevelOffset: int = 2, getPromotionItems: bool = True) -> None:
    if filters is None:
        filters = []

    data["variables"]["queryInput"]["categoryId"] = category_id
    data["variables"]["queryInput"]["pagination"]["offset"] = offset
    data["variables"]["queryInput"]["pagination"]["limit"] = limit
    data["variables"]["queryInput"]["showAdultContent"] = showAdultContent
    data["variables"]["queryInput"]["filters"] = filters
    data["variables"]["queryInput"]["sort"] = sort
    data["variables"]["queryInput"]["correctQuery"] = correctQuery
    data["variables"]["queryInput"]["getFastCategories"] = getFastCategories
    data["variables"]["queryInput"]["fastCategoriesLevelOffset"] = fastCategoriesLevelOffset
    data["variables"]["queryInput"]["getPromotionItems"] = getPromotionItems


def generate_query(save_json=False, **kwargs):
    defaults = {
        "offset": 0,
        "limit": 1,
        "showAdultContent": "TRUE",
        "filters": "[]",
        "sort": "BY_RELEVANCE_DESC",
        "correctQuery": "false",
        "getFastCategories": "true",
        "fastCategoriesLevelOffset": 2,
        "getPromotionItems": "true"
    }

    data = {
        "operationName": "getMakeSearch",
        "variables": {
            "queryInput": {
                "categoryId": "0",
                "showAdultContent": "TRUE",
                "filters": [],
                "sort": "BY_RELEVANCE_DESC",
                "pagination": {
                    "offset": 0,
                    "limit": 0
                },
                "correctQuery": False,
                "getFastCategories": False,
                "fastCategoriesLevelOffset": 0,
                "getPromotionItems": False
            }
        },
        "query": """
        query getMakeSearch($queryInput: MakeSearchQueryInput!) {
            makeSearch(query: $queryInput) {
                category {
                    id
                    title
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
                total
            }
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
        }
        """
    }

    # Update default values with any kwargs provided
    defaults.update(kwargs)

    # Update the data dictionary with the new values
    data["variables"]["queryInput"] = {
        "categoryId": defaults.get("category_id"),
        "pagination": {
            "offset": defaults["offset"],
            "limit": defaults["limit"]
        },
        "showAdultContent": defaults["showAdultContent"],
        "filters": defaults["filters"],
        "sort": defaults["sort"],
        "correctQuery": defaults["correctQuery"],
        "getFastCategories": defaults["getFastCategories"],
        "fastCategoriesLevelOffset": defaults["fastCategoriesLevelOffset"],
        "getPromotionItems": defaults["getPromotionItems"]
    }

    if save_json:
        # Save the data dictionary to a JSON file
        with open('graphql_query_data.json', 'w', encoding='utf-8') as json_file:
            json.dump(data, json_file, indent=4, ensure_ascii=False)

        logger.info("GraphQL query data saved to graphql_query_data.json")

    return data


if __name__ == "__main__":
    generate_query(True)
