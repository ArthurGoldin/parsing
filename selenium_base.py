from seleniumbase import SB


def verify_success(sb):
    sb.assert_element('img[alt="Logo Assembly"]', timeout=8)
    sb.sleep(4)


with SB(uc_cdp=True, guest_mode=True) as sb:
    sb.open("https://uzum.uz/ru")
    try:
        verify_success(sb)
    except Exception:
        if sb.is_element_visible('input[value*="Verify"]'):
            sb.click('input[value*="Verify"]')
        elif sb.is_element_visible('iframe[title*="challenge"]'):
            sb.switch_to_frame('iframe[title*="challenge"]')
            sb.click("span.mark")
        else:
            raise Exception("Detected!")
        try:
            verify_success(sb)
        except Exception:
            raise Exception("Detected!")
