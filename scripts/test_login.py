"""쿠팡 로그인 테스트 스크립트"""
import sys
from pathlib import Path
import asyncio

# 프로젝트 루트를 파이썬 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.account import Account
from app.utils.encryption import encryptor
from uploaders.playwright_uploader import PlaywrightUploader


async def test_login_all_accounts():
    """5개 계정 로그인 테스트"""
    print("="*60)
    print("쿠팡 계정 로그인 테스트")
    print("="*60)

    db = SessionLocal()

    try:
        accounts = db.query(Account).filter(Account.is_active == True).all()

        if not accounts:
            print("❌ 등록된 계정이 없습니다.")
            print("먼저 'python scripts/register_accounts.py' 실행하세요.")
            return

        print(f"\n테스트할 계정: {len(accounts)}개\n")

        results = []

        for acc in accounts:
            print(f"🔐 {acc.account_name} ({acc.email}) 로그인 시도...")

            # 비밀번호 복호화
            password = encryptor.decrypt(acc.password_encrypted)

            # Playwright 업로더로 로그인
            uploader = PlaywrightUploader(account_id=acc.id)

            try:
                success = await uploader.login(acc.email, password)

                if success:
                    print(f"   ✅ 로그인 성공!")
                    # DB 업데이트
                    from datetime import datetime
                    acc.last_login_at = datetime.utcnow()
                    db.commit()
                    results.append((acc.account_name, True, "성공"))
                else:
                    print(f"   ❌ 로그인 실패")
                    results.append((acc.account_name, False, "실패"))

            except Exception as e:
                print(f"   ❌ 오류: {e}")
                results.append((acc.account_name, False, str(e)))

            print()

        # 결과 요약
        print("="*60)
        print("로그인 테스트 결과")
        print("="*60)

        success_count = sum(1 for _, success, _ in results if success)

        for name, success, msg in results:
            status = "✅" if success else "❌"
            print(f"{status} {name}: {msg}")

        print(f"\n성공: {success_count}/{len(results)}")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("\n⚠️  주의: 이 스크립트는 브라우저를 열어서 실제 로그인을 시도합니다.")
    print("⚠️  쿠팡 보안 정책에 따라 CAPTCHA가 나올 수 있습니다.")
    print()

    response = input("계속하시겠습니까? (y/n): ")

    if response.lower() == 'y':
        asyncio.run(test_login_all_accounts())
    else:
        print("취소되었습니다.")
