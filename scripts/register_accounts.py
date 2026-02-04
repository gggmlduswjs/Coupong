"""계정 정보를 암호화하여 DB에 등록하는 스크립트"""
import sys
from pathlib import Path
import os
from dotenv import load_dotenv

# 프로젝트 루트를 파이썬 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# .env 파일 로드
load_dotenv()

from app.database import SessionLocal, init_db
from app.models.account import Account
from app.utils.encryption import encryptor
from datetime import datetime


def register_accounts():
    """5개 계정 정보를 DB에 등록"""
    print("="*60)
    print("쿠팡 계정 정보 등록 (암호화)")
    print("="*60)

    # DB 초기화
    init_db()

    db = SessionLocal()

    try:
        # 5개 계정 정보
        accounts_data = []
        for i in range(1, 6):
            account_id = os.getenv(f"COUPANG_ID_{i}")
            account_pw = os.getenv(f"COUPANG_PW_{i}")

            if not account_id or not account_pw:
                print(f"⚠️  계정 {i} 정보 없음 (건너뜀)")
                continue

            accounts_data.append({
                "name": f"account_{i}",
                "email": account_id,
                "password": account_pw
            })

        print(f"\n등록할 계정: {len(accounts_data)}개")

        # DB에 등록
        registered_count = 0
        updated_count = 0

        for data in accounts_data:
            # 중복 체크
            existing = db.query(Account).filter(
                Account.account_name == data["name"]
            ).first()

            if existing:
                # 업데이트
                existing.email = data["email"]
                existing.password_encrypted = encryptor.encrypt(data["password"])
                existing.updated_at = datetime.utcnow()
                print(f"🔄 업데이트: {data['name']} ({data['email']})")
                updated_count += 1
            else:
                # 새로 등록
                account = Account(
                    account_name=data["name"],
                    email=data["email"],
                    password_encrypted=encryptor.encrypt(data["password"]),
                    is_active=True
                )
                db.add(account)
                print(f"✅ 신규 등록: {data['name']} ({data['email']})")
                registered_count += 1

        db.commit()

        print("\n" + "="*60)
        print(f"✅ 등록 완료!")
        print(f"   신규: {registered_count}개")
        print(f"   업데이트: {updated_count}개")
        print("="*60)

        # 등록된 계정 확인
        print("\n📋 등록된 계정 목록:")
        accounts = db.query(Account).all()
        for acc in accounts:
            status = "🟢 활성" if acc.is_active else "🔴 비활성"
            print(f"   {status} {acc.account_name}: {acc.email}")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def test_encryption():
    """암호화/복호화 테스트"""
    print("\n" + "="*60)
    print("암호화 테스트")
    print("="*60)

    test_password = "test_password_123!"
    encrypted = encryptor.encrypt(test_password)
    decrypted = encryptor.decrypt(encrypted)

    print(f"원본: {test_password}")
    print(f"암호화: {encrypted[:50]}...")
    print(f"복호화: {decrypted}")
    print(f"일치: {'✅ 성공' if test_password == decrypted else '❌ 실패'}")


if __name__ == "__main__":
    # 암호화 테스트
    test_encryption()

    # 계정 등록
    register_accounts()

    print("\n🎉 완료! 이제 계정 정보가 안전하게 암호화되어 저장되었습니다.")
    print("\n다음 단계:")
    print("1. python scripts/quick_start.py  # 크롤링 테스트")
    print("2. python scripts/test_login.py   # 로그인 테스트 (선택)")
