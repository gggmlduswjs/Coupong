"""교보문고 페이지 구조 확인"""
import asyncio
from playwright.async_api import async_playwright


async def inspect_kyobo():
    """교보문고 검색 페이지 HTML 구조 확인"""

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 교보문고 검색 페이지
        url = "https://www.kyobobook.co.kr/search?keyword=초등수학"
        print(f"Accessing: {url}")

        await page.goto(url, timeout=30000)
        await page.wait_for_timeout(3000)

        # 페이지 제목 확인
        title = await page.title()
        print(f"\nPage title: {title}")

        # 가능한 상품 목록 선택자들 시도
        selectors = [
            ".prod_item",
            ".product_item",
            ".product-item",
            "[class*='prod']",
            "[class*='product']",
            ".list_search_result li",
            ".list_product li",
        ]

        print("\nTrying selectors:")
        for selector in selectors:
            elements = await page.query_selector_all(selector)
            print(f"  {selector}: {len(elements)} elements")

            if len(elements) > 0:
                print(f"\n    ✓ Found {len(elements)} products with: {selector}")

                # 첫 번째 요소의 HTML 확인
                if elements:
                    first_html = await elements[0].inner_html()
                    print(f"\n    First element HTML (first 500 chars):")
                    print(f"    {first_html[:500]}")

        # 5초 대기 (수동 확인)
        print("\nBrowser will close in 5 seconds...")
        await page.wait_for_timeout(5000)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(inspect_kyobo())
