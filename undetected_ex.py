import undetected_chromedriver as uc
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

chrome_options = webdriver.ChromeOptions()
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--headless')
chrome_options.add_argument('--enable-javascript')
chrome_options.add_argument('--disable-gpu')
user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15'
chrome_options.add_argument('User-Agent={0}'.format(user_agent))
chrome_options.add_experimental_option(
    "excludeSwitches", ["enable-automation"])
chrome_options.add_experimental_option('useAutomationExtension', True)

service = Service(ChromeDriverManager().install())

driver = uc.Chrome(service=service,
                   chrome_options=chrome_options, service_args=['--quiet'])
driver.implicitly_wait(6.5)

try:
    driver.get("https://google.com")
    driver.save_screenshot("google.png")
except Exception as e:
    print(f"Error in driver get: {e}")
finally:
    driver.close()
    driver.quit()
