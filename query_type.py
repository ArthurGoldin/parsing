introspection_query = {
    "query": """
    {
      __schema {
        types {
          name
          kind
          fields {
            name
            description
            args {
              name
              type {
                name
                kind
                ofType {
                  name
                  kind
                }
              }
              defaultValue
            }
            type {
              name
              kind
              ofType {
                name
                kind
              }
            }
          }
        }
      }
    }
    """
}
js_code = generate_fetch_js_code(
    introspection_query, auth_token, graphql_url)

driver.get(main_url)
WebDriverWait(driver, 20).until(EC.title_contains("Uzum Market"))

logger.info(f"PAGE LOADED: {driver.title}")
driver.execute_script(js_code)

 WebDriverWait(driver, 20).until(lambda d: d.execute_script(
      "return window.graphqlResponse") is not None)
  response = driver.execute_script("return window.graphqlResponse;")

   if check_response_with_retry(response):
        json_file_name = os.path.join(data_dir, f'query_fields.json')
        # Save JSON response
        with open(json_file_name, 'w', encoding='utf-8') as json_file:
            json.dump(response, json_file,
                      indent=4, ensure_ascii=False)
        logger.info(f"Response saved to {json_file_name}")

        is_done = True
    else:
        is_done = True
