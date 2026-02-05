"""
쿠팡 WING API 연결 테스트
=========================
IP 등록 후 이 스크립트로 간단 테스트

사용법:
    python scripts/test_wing_api.py
"""
import sys
import os
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from app.api.coupang_wing_client import CoupangWingClient
from app.constants import WING_ACCOUNT_ENV_MAP
import json


def test_all_accounts():
    print("=" * 60)
    print("  쿠팡 WING API 연결 테스트")
    print(f"  현재 IP: ", end="")

    try:
        import requests
        ip = requests.get("https://api.ipify.org", timeout=5).text
        print(ip)
    except Exception:
        print("확인 불가")

    print("=" * 60)

    results = {}

    for account_name, env_prefix in WING_ACCOUNT_ENV_MAP.items():
        vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID")
        access_key = os.getenv(f"{env_prefix}_ACCESS_KEY")
        secret_key = os.getenv(f"{env_prefix}_SECRET_KEY")

        if not all([vendor_id, access_key, secret_key]):
            print(f"\n  {account_name}: 크레덴셜 없음, 건너뜀")
            results[account_name] = "NO_CREDENTIALS"
            continue

        client = CoupangWingClient(vendor_id, access_key, secret_key)

        print(f"\n  {account_name} (vendor_id={vendor_id})...")

        try:
            params = {"vendorId": vendor_id, "maxPerPage": "1"}
            result = client._request("GET", client.SELLER_PRODUCTS_PATH, params=params)

            data = result.get("data", [])
            if isinstance(data, list):
                count = len(data)
            elif isinstance(data, dict):
                count = len(data.get("products", data.get("items", [])))
            else:
                count = 0

            print(f"    [OK] 연결 성공! (상품 {count}개 조회)")
            results[account_name] = "SUCCESS"

            # 출고지 조회 시도
            try:
                shipping = client.get_outbound_shipping_places()
                print(f"    [OK] 출고지 조회 성공: {json.dumps(shipping, ensure_ascii=False)[:200]}")
            except Exception as e:
                print(f"    [WARN] 출고지 조회: {str(e)[:80]}")

        except Exception as e:
            err = str(e)
            if "403" in err and "ip" in err.lower():
                print(f"    [FAIL] IP 차단 (화이트리스트 미등록 또는 반영 대기중)")
                results[account_name] = "IP_BLOCKED"
            else:
                print(f"    [FAIL] 오류: {err[:100]}")
                results[account_name] = f"ERROR: {err[:50]}"

    # 요약
    print("\n" + "=" * 60)
    print("  결과 요약")
    print("=" * 60)
    for name, status in results.items():
        icon = "[OK]" if status == "SUCCESS" else "[FAIL]"
        print(f"  {icon} {name}: {status}")
    print("=" * 60)

    success_count = sum(1 for s in results.values() if s == "SUCCESS")
    print(f"\n  {success_count}/{len(results)} 계정 연결 성공")

    return results


if __name__ == "__main__":
    test_all_accounts()
