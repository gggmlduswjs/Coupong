"""교보문고 페이지 구조 상세 분석"""
import asyncio
from playwright.async_api import async_playwright


async def debug_kyobo():
    """교보문고 실제 구조 확인"""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            url = "https://www.kyobobook.co.kr/search?keyword=초등수학&target=total"
            print(f"Accessing: {url}")

            await page.goto(url, timeout=60000)
            print("Page loaded. Waiting for content...")

            # 긴 대기 시간 (동적 로딩)
            await page.wait_for_timeout(5000)

            # 페이지 HTML 구조 확인
            print("\n" + "="*60)
            print("Analyzing page structure...")
            print("="*60)

            # 1. 모든 링크 확인
            links = await page.query_selector_all("a[href*='/product/']")
            print(f"\n1. Product links found: {len(links)}")

            if links:
                first_link = await links[0].get_attribute("href")
                print(f"   First link: {first_link}")

            # 2. 이미지 확인
            images = await page.query_selector_all("img[alt]")
            print(f"\n2. Images with alt: {len(images)}")

            if images:
                first_img_alt = await images[0].get_attribute("alt")
                first_img_src = await images[0].get_attribute("src")
                print(f"   First image alt: {first_img_alt}")
                print(f"   First image src: {first_img_src[:50]}...")

            # 3. 가격 정보
            price_elements = await page.query_selector_all("[class*='price']")
            print(f"\n3. Price elements: {len(price_elements)}")

            # 4. 상품 카드/리스트 아이템
            possible_selectors = [
                ".prod_item",
                ".product_item",
                ".prod_area",
                ".product",
                "[class*='prod']",
                "[class*='product']",
                "[class*='item']",
                "li[class*='prod']",
                "div[class*='prod']",
            ]

            print("\n4. Trying product container selectors:")
            for selector in possible_selectors:
                elements = await page.query_selector_all(selector)
                if len(elements) > 0:
                    print(f"   ✓ {selector}: {len(elements)} found")

                    # 첫 번째 요소의 내용 확인
                    if elements:
                        first_html = await elements[0].inner_html()
                        print(f"      HTML preview: {first_html[:200]}...")
                        break
                else:
                    print(f"   ✗ {selector}: 0")

            # 5. 실제 상품 정보 추출 시도
            print("\n5. Attempting to extract product info...")

            # 네트워크 요청 확인
            print("\n6. Checking network requests...")
            print("   (Check browser DevTools Network tab)")

            # 30초 대기 (수동 확인)
            print("\n" + "="*60)
            print("Browser will stay open for 30 seconds")
            print("Please check the page structure manually")
            print("="*60)
            await page.wait_for_timeout(30000)

        except Exception as e:
            print(f"\nError: {e}")
            import traceback
            traceback.print_exc()

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(debug_kyobo())
