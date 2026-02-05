"""
출고지/반품지 코드 조회 및 DB 저장 + 카테고리 코드 확인
===========================================================
5개 계정의 출고지/반품지 코드를 WING API로 조회하여 accounts 테이블에 저장
도서 카테고리 코드를 카테고리 추천 API로 확인

사용법:
    python scripts/setup_shipping_places.py              # 전체 5계정
    python scripts/setup_shipping_places.py --account 007-book  # 특정 계정
    python scripts/setup_shipping_places.py --check-category    # 카테고리 확인만
"""
import sys
import os
import json
import argparse
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import inspect, text
from app.database import SessionLocal, init_db, engine
from app.models.account import Account
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from app.constants import WING_ACCOUNT_ENV_MAP

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def _migrate_account_columns():
    """Account 테이블에 WING API 컬럼 추가 (필요시)"""
    try:
        inspector = inspect(engine)
        existing_cols = {col["name"] for col in inspector.get_columns("accounts")}
    except Exception:
        return

    new_cols = {
        "vendor_id": "VARCHAR(20)",
        "wing_access_key": "VARCHAR(100)",
        "wing_secret_key": "VARCHAR(100)",
        "wing_api_enabled": "BOOLEAN DEFAULT 0",
        "outbound_shipping_code": "VARCHAR(50)",
        "return_center_code": "VARCHAR(50)",
    }

    with engine.connect() as conn:
        for col_name, col_type in new_cols.items():
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE accounts ADD COLUMN {col_name} {col_type}"))
                logger.info(f"  컬럼 추가: accounts.{col_name}")
        conn.commit()


def create_wing_client_from_env(account_name: str) -> CoupangWingClient:
    """환경변수에서 직접 WING 클라이언트 생성"""
    env_prefix = WING_ACCOUNT_ENV_MAP.get(account_name)
    if not env_prefix:
        raise ValueError(f"알 수 없는 계정: {account_name}")

    vendor_id = os.getenv(f"{env_prefix}_VENDOR_ID")
    access_key = os.getenv(f"{env_prefix}_ACCESS_KEY")
    secret_key = os.getenv(f"{env_prefix}_SECRET_KEY")

    if not all([vendor_id, access_key, secret_key]):
        raise ValueError(f"{account_name}: .env에 크레덴셜 없음")

    return CoupangWingClient(vendor_id, access_key, secret_key)


def query_shipping_places(account_name: str) -> dict:
    """
    단일 계정의 출고지/반품지 코드 조회

    Returns:
        {
            "outbound": [{"code": "...", "name": "...", "address": "..."}],
            "return": [{"code": "...", "name": "...", "address": "..."}],
        }
    """
    client = create_wing_client_from_env(account_name)
    result = {"outbound": [], "return": []}

    # 출고지 조회
    try:
        outbound_data = client.get_outbound_shipping_places()
        logger.info(f"  출고지 원본 응답: {json.dumps(outbound_data, ensure_ascii=False)[:500]}")

        # 응답 구조 파싱 (여러 가능한 형태)
        places = _extract_shipping_places(outbound_data)
        result["outbound"] = places

        if places:
            logger.info(f"  [OK] 출고지 {len(places)}개 발견")
            for p in places:
                logger.info(f"       - {p.get('code', '?')}: {p.get('name', '?')} ({p.get('address', '?')})")
        else:
            logger.warning(f"  [WARN] 출고지 없음 (등록 필요)")

    except CoupangWingError as e:
        logger.error(f"  [FAIL] 출고지 조회 실패: {e}")

    # 반품지 조회
    try:
        return_data = client.get_return_shipping_centers()
        logger.info(f"  반품지 원본 응답: {json.dumps(return_data, ensure_ascii=False)[:500]}")

        places = _extract_shipping_places(return_data)
        result["return"] = places

        if places:
            logger.info(f"  [OK] 반품지 {len(places)}개 발견")
            for p in places:
                logger.info(f"       - {p.get('code', '?')}: {p.get('name', '?')} ({p.get('address', '?')})")
        else:
            logger.warning(f"  [WARN] 반품지 없음 (등록 필요)")

    except CoupangWingError as e:
        logger.error(f"  [FAIL] 반품지 조회 실패: {e}")

    return result


def _extract_shipping_places(api_response: dict) -> list:
    """
    API 응답에서 출고지/반품지 목록 추출

    응답 구조가 다양할 수 있어 여러 경로를 시도:
    - data.content[].shippingPlaceCode / shippingPlaceName
    - data[].outboundShippingPlaceCode / outboundShippingPlaceName
    - data.content[].returnCenterCode / returnCenterName
    """
    places = []

    # data 추출
    data = api_response.get("data", api_response)

    # content 배열 형태 (일반적)
    if isinstance(data, dict):
        content = data.get("content", data.get("shippingPlaces", data.get("items", [])))
        if isinstance(content, list):
            for item in content:
                place = _parse_shipping_place(item)
                if place:
                    places.append(place)
        elif not content:
            # data 자체가 단일 레코드일 수 있음
            place = _parse_shipping_place(data)
            if place:
                places.append(place)

    elif isinstance(data, list):
        for item in data:
            place = _parse_shipping_place(item)
            if place:
                places.append(place)

    return places


def _parse_shipping_place(item: dict) -> dict:
    """단일 출고지/반품지 항목 파싱"""
    if not isinstance(item, dict):
        return None

    # 출고지 코드 (다양한 필드명)
    code = (
        item.get("shippingPlaceCode")
        or item.get("outboundShippingPlaceCode")
        or item.get("returnCenterCode")
        or item.get("placeCode")
        or item.get("code")
        or item.get("shippingPlaceId")
        or str(item.get("id", ""))
    )

    name = (
        item.get("shippingPlaceName")
        or item.get("outboundShippingPlaceName")
        or item.get("returnCenterName")
        or item.get("placeName")
        or item.get("name")
        or ""
    )

    address = (
        item.get("placeAddresses", [{}])[0].get("addr1", "") if item.get("placeAddresses") else
        item.get("address")
        or item.get("addr1")
        or item.get("fullAddress")
        or ""
    )

    if code:
        return {"code": str(code), "name": name, "address": address}

    return None


def save_shipping_codes_to_db(db, account_name: str, outbound_code: str, return_code: str):
    """출고지/반품지 코드를 accounts 테이블에 저장"""
    account = db.query(Account).filter(
        Account.account_name == account_name
    ).first()

    if not account:
        logger.warning(f"  DB에 {account_name} 계정 없음, 건너뜀")
        return False

    updated = False
    if outbound_code and account.outbound_shipping_code != outbound_code:
        account.outbound_shipping_code = outbound_code
        updated = True
        logger.info(f"  [OK] 출고지 코드 저장: {outbound_code}")

    if return_code and account.return_center_code != return_code:
        account.return_center_code = return_code
        updated = True
        logger.info(f"  [OK] 반품지 코드 저장: {return_code}")

    if updated:
        db.commit()
    else:
        logger.info(f"  변경 없음 (이미 저장됨)")

    return updated


def check_book_category(account_name: str = "007-book"):
    """
    도서 카테고리 코드 확인

    카테고리 추천 API로 도서 상품명을 전송하여 실제 카테고리 코드 확인
    """
    client = create_wing_client_from_env(account_name)

    print("\n" + "=" * 60)
    print("  도서 카테고리 코드 확인")
    print("=" * 60)

    # 여러 도서 상품명으로 테스트
    test_names = [
        "2025 수능완성 국어영역",
        "개념원리 수학 상",
        "EBS 수능특강 영어",
        "마더텅 수학 기출문제집",
    ]

    categories = {}

    for name in test_names:
        try:
            result = client.recommend_category(name)
            logger.info(f"  카테고리 추천 응답 ({name}): {json.dumps(result, ensure_ascii=False)[:300]}")

            # 응답에서 카테고리 코드 추출
            # 응답 형식: {"data": {"autoCategorizationPredictionResultType": "SUCCESS", "predictedCategoryId": "76239", "predictedCategoryName": "기타교재"}}
            data = result.get("data", result)
            code = ""
            cat_name = ""
            if isinstance(data, dict):
                code = str(data.get("predictedCategoryId", ""))
                cat_name = data.get("predictedCategoryName", "")
                if not code:
                    # 다른 형식 시도
                    code = str(data.get("displayCategoryCode", ""))
                    cat_name = data.get("displayCategoryName", "")
            elif isinstance(data, list) and data:
                code = str(data[0].get("predictedCategoryId", data[0].get("displayCategoryCode", "")))
                cat_name = data[0].get("predictedCategoryName", data[0].get("displayCategoryName", ""))

            if code:
                print(f"  {name}")
                print(f"    -> 카테고리: {code} ({cat_name})")
                categories[code] = cat_name
            else:
                print(f"  {name}")
                print(f"    -> 카테고리 추천 결과 없음")
                print(f"    -> 원본 응답: {json.dumps(result, ensure_ascii=False)[:200]}")

        except CoupangWingError as e:
            print(f"  {name}")
            print(f"    -> [FAIL] {e}")

    # 결과 요약
    print("\n" + "-" * 40)
    print("  카테고리 코드 요약:")
    if categories:
        for code, name in categories.items():
            print(f"    {code}: {name}")
    else:
        print("    카테고리 추천 결과 없음 - 수동 확인 필요")
        print("    현재 기본값: BOOK_CATEGORY_CODE = 76001")
    print("=" * 60)

    return categories


def run_setup(account_names=None, check_category=False):
    """메인 실행"""
    print("\n" + "=" * 60)
    print("  출고지/반품지 코드 조회 및 DB 저장")
    print("=" * 60)

    init_db()
    _migrate_account_columns()

    # 대상 계정
    target_accounts = account_names or list(WING_ACCOUNT_ENV_MAP.keys())

    all_results = {}

    for account_name in target_accounts:
        if account_name not in WING_ACCOUNT_ENV_MAP:
            logger.warning(f"알 수 없는 계정: {account_name}")
            continue

        print(f"\n--- {account_name} ---")

        # 출고지/반품지 조회
        shipping = query_shipping_places(account_name)
        all_results[account_name] = shipping

        # 첫 번째 출고지/반품지 코드를 DB에 저장
        outbound_code = ""
        if shipping["outbound"]:
            outbound_code = shipping["outbound"][0]["code"]

        return_code = ""
        if shipping["return"]:
            return_code = shipping["return"][0]["code"]

        if outbound_code or return_code:
            db = SessionLocal()
            try:
                save_shipping_codes_to_db(db, account_name, outbound_code, return_code)
            finally:
                db.close()

    # 결과 요약
    print("\n" + "=" * 60)
    print("  결과 요약")
    print("=" * 60)
    print(f"  {'계정':<12} {'출고지코드':<20} {'반품지코드':<20}")
    print(f"  {'-'*12} {'-'*20} {'-'*20}")

    for name, data in all_results.items():
        out_code = data["outbound"][0]["code"] if data["outbound"] else "(없음)"
        ret_code = data["return"][0]["code"] if data["return"] else "(없음)"
        print(f"  {name:<12} {out_code:<20} {ret_code:<20}")

    print("=" * 60)

    # 카테고리 확인
    if check_category:
        check_book_category()

    return all_results


def main():
    parser = argparse.ArgumentParser(description="출고지/반품지 코드 조회 및 저장")
    parser.add_argument(
        "--account", nargs="+",
        help="특정 계정만 (예: --account 007-book)"
    )
    parser.add_argument(
        "--check-category", action="store_true",
        help="도서 카테고리 코드도 확인"
    )

    args = parser.parse_args()

    run_setup(
        account_names=args.account,
        check_category=args.check_category,
    )


if __name__ == "__main__":
    main()
