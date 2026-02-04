"""쿠팡 판매자센터 페이지 구조 확인"""
import sys
from pathlib import Path
import asyncio

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from playwright.async_api import async_playwright
from app.database import SessionLocal
from app.models.account import Account
from app.utils.encryption import encryptor


async def inspect_coupang_login():
    """쿠팡 판매자센터 로그인 페이지 확인"""

    # 첫 번째 계정 가져오기
    db = SessionLocal()
    account = db.query(Account).filter(Account.is_active == True).first()

    if not account:
        print("No active accounts found. Run: python scripts/register_accounts.py")
        return

    email = account.email
    password = encryptor.decrypt(account.password_encrypted)

    print(f"Testing login for: {account.account_name} ({email})")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        try:
            # 쿠팡 판매자센터 로그인 페이지
            login_url = "https://wing.coupang.com/login"
            print(f"\n1. Accessing: {login_url}")
            await page.goto(login_url, timeout=30000)
            await page.wait_for_timeout(2000)

            print("2. Looking for login form...")

            # 가능한 입력 필드 선택자들
            email_selectors = [
                "input[name='loginId']",
                "input[name='username']",
                "input[name='email']",
                "input[type='email']",
                "#loginId",
                "#username",
            ]

            password_selectors = [
                "input[name='password']",
                "input[type='password']",
                "#password",
            ]

            # 이메일 필드 찾기
            email_field = None
            for selector in email_selectors:
                try:
                    email_field = await page.query_selector(selector)
                    if email_field:
                        print(f"   Found email field: {selector}")
                        break
                except:
                    continue

            # 비밀번호 필드 찾기
            password_field = None
            for selector in password_selectors:
                try:
                    password_field = await page.query_selector(selector)
                    if password_field:
                        print(f"   Found password field: {selector}")
                        break
                except:
                    continue

            if email_field and password_field:
                print("\n3. Filling login form...")

                # 입력
                await email_field.fill(email)
                await page.wait_for_timeout(1000)

                await password_field.fill(password)
                await page.wait_for_timeout(1000)

                print("4. Filled. Check the browser window.")
                print("\n   You can:")
                print("   - Manually solve CAPTCHA if needed")
                print("   - Click login button")
                print("   - Check if login succeeded")

                # 30초 대기 (수동 로그인 확인용)
                print("\n   Waiting 30 seconds for manual inspection...")
                await page.wait_for_timeout(30000)

                # 현재 URL 확인
                current_url = page.url
                print(f"\n5. Current URL: {current_url}")

                if "dashboard" in current_url or "home" in current_url or "wing.coupang.com" in current_url and "login" not in current_url:
                    print("   ✓ Login appears successful!")

                    # 세션 저장
                    session_dir = project_root / "sessions"
                    session_dir.mkdir(exist_ok=True)
                    session_file = session_dir / f"account_{account.id}.json"

                    await context.storage_state(path=str(session_file))
                    print(f"   ✓ Session saved: {session_file}")
                else:
                    print("   ? Still on login page or unknown page")

            else:
                print("\n✗ Could not find login form fields")
                print("   The page structure might be different")

                # 페이지 HTML 일부 출력
                html = await page.content()
                print(f"\n   Page HTML (first 500 chars):")
                print(f"   {html[:500]}")

        except Exception as e:
            print(f"\nError: {e}")

        finally:
            await browser.close()
            db.close()


if __name__ == "__main__":
    print("Coupang Seller Center - Login Inspector")
    print("=" * 60)
    asyncio.run(inspect_coupang_login())
