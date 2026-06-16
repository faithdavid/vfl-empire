from playwright.sync_api import sync_playwright
p=sync_playwright().start()
b=p.chromium.connect_over_cdp('http://localhost:9222')
pg=b.contexts[0].pages[0]

print("Page URL:", pg.url)
print("Page Title:", pg.title())

# Dump all elements containing 'NGN'
print("\n--- Elements containing 'NGN' ---")
el_ngn = pg.locator('*:has-text("NGN")').all()
for i, el in enumerate(el_ngn[:15]):
    try:
        tag = el.evaluate("el => el.tagName")
        cls = el.get_attribute("class")
        text = el.inner_text()
        print(f"[{i}] {tag} class='{cls}': {text[:100]}")
    except Exception as e:
        pass

# Search for any text match like balance
print("\n--- Checking for class names with 'balance' ---")
el_bal = pg.locator('[class*="balance"], [class*="bal"]').all()
for i, el in enumerate(el_bal[:15]):
    try:
        tag = el.evaluate("el => el.tagName")
        cls = el.get_attribute("class")
        text = el.inner_text()
        print(f"[{i}] {tag} class='{cls}': {text[:100]}")
    except:
        pass

b.close()
p.stop()
