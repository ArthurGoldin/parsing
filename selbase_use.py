from seleniumbase import SB


def open_the_turnstile_page(sb):
    url = "https://uzum.uz/ru"
    if sb.undetectable == True:
        print("UC Mode")
        sb.driver.uc_open(url)
    else:
        print("No UC Mode")
        sb.driver.get(url)


def click_turnstile_and_verify(sb):
    try:
        if sb.is_element_present("iframe[title='Widget containing a Cloudflare security challenge']"):
            print("CAPTCHA PRESENT")

            sb.switch_to_frame("iframe")
            sb.driver.uc_click("span")
            sb.assert_element("img#captcha-success", timeout=3)
        else:
            print("NO CAPTCHA or BYPASSED")
    except Exception as e:
        print(f"Something went wrong: {e}")


with SB(uc=True, test=True) as sb:
    open_the_turnstile_page(sb)
    try:
        click_turnstile_and_verify(sb)
    except Exception as e:
        print(f"No CAPTCHA detected: {e}")

    try:
        sb.highlight("div.banner-block")
        # sb.assert_text("This Text is Purple", "#pText")
    except Exception as e:
        print(f"Something went wrong: {e}")
    sb.sleep(0.5)
