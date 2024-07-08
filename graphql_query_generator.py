import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger()


def set_query_variables(data: dict, category_id: str, offset: int = 0, limit: int = 1, sort: str = "BY_RELEVANCE_DESC", showAdultContent: str = "TRUE", filters: list = [], correctQuery: bool = False, getFastCategories: bool = True, fastCategoriesLevelOffset: int = 2, getPromotionItems: bool = True) -> None:
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
        "limit": 100,
        "showAdultContent": "TRUE",
        "filters": "[]",
        "sort": "BY_RELEVANCE_DESC",
        "correctQuery": "true",
        "getFastCategories": "false",
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
                    "limit": 100
                },
                "correctQuery": True,
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
                    catalogCard {
                        ...SkuGroupCardFragment
                    }
                }
                total
            }
        }
        fragment SkuGroupCardFragment on SkuGroupCard {
            ...DefaultCardFragment
        }
        fragment DefaultCardFragment on CatalogCard {
            productId
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
