"""스케줄링용 완전 자동 업데이트 스크립트 (사용자 입력 없음)"""
import sys
from pathlib import Path
import os
from datetime import datetime, timedelta
import logging

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from crawlers.aladin_api_crawler import AladinAPICrawler
from app.database import SessionLocal
from app.models.kyobo_product import KyoboProduct
from app.models.account import Account
from uploaders.coupang_csv_generator import CoupangCSVGenerator
from config.publishers import PUBLISHERS, get_publisher_info, meets_free_shipping

# 로깅 설정
log_dir = project_root / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_dir / f"auto_update_{datetime.now().strftime('%Y%m%d')}.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# 설정
CONFIG = {
    "max_per_publisher": 20,        # 출판사당 최대 검색 개수
    "recent_days": 180,              # 최근 N일 이내 출간 도서만
    "min_price": 5000,               # 최소 가격
    "max_price": 100000,             # 최대 가격
}


def main():
    """완전 자동 모드"""
    logger.info("="*80)
    logger.info("출판사별 최신 도서 자동 업데이트 시작")
    logger.info("="*80)

    # TTBKey 확인
    ttb_key = os.getenv("ALADIN_TTB_KEY")
    if not ttb_key:
        logger.error("ALADIN_TTB_KEY가 설정되지 않았습니다.")
        return

    # 크롤러 초기화
    crawler = AladinAPICrawler(ttb_key=ttb_key)

    # 설정 출력
    logger.info(f"설정:")
    logger.info(f"  - 출판사: {len(PUBLISHERS)}개")
    logger.info(f"  - 출판사당 최대: {CONFIG['max_per_publisher']}개")
    logger.info(f"  - 최근: {CONFIG['recent_days']}일 이내")
    logger.info(f"  - 가격대: {CONFIG['min_price']:,}원 ~ {CONFIG['max_price']:,}원")

    cutoff_date = datetime.now() - timedelta(days=CONFIG['recent_days'])

    # 출판사별 검색
    all_new_products = []

    for pub in PUBLISHERS:
        pub_name = pub["name"]
        logger.info(f"\n[{pub_name}] 검색 중...")

        try:
            products = crawler.search_by_keyword(pub_name, max_results=CONFIG['max_per_publisher'])

            for p in products:
                # 출판사 필터링
                if pub_name not in p.get("publisher", ""):
                    continue

                # 최신도서 필터링
                pub_date = p.get("publish_date")
                if pub_date and pub_date < cutoff_date.date():
                    continue

                # 가격 범위 필터링
                if not (CONFIG['min_price'] <= p['original_price'] <= CONFIG['max_price']):
                    logger.debug(f"  가격 범위 미충족: {p['title'][:30]}")
                    continue

                # 무료배송 기준 체크
                sale_price = int(p["original_price"] * 0.9)
                if not meets_free_shipping(pub_name, sale_price):
                    logger.debug(f"  무료배송 미충족: {p['title'][:30]} ({sale_price:,}원)")
                    continue

                all_new_products.append(p)
                logger.info(f"  ✓ {p['title'][:50]} ({p['original_price']:,}원)")

        except Exception as e:
            logger.error(f"  오류: {e}")
            continue

    logger.info(f"\n총 검색 결과: {len(all_new_products)}개")

    if not all_new_products:
        logger.info("새로운 도서가 없습니다.")
        return

    # DB 저장
    saved_count = save_to_db(all_new_products)

    if saved_count == 0:
        logger.info("저장된 새 도서가 없습니다. (모두 중복)")
        return

    # CSV 생성
    generate_csvs(all_new_products)

    logger.info("\n" + "="*80)
    logger.info(f"자동 업데이트 완료: {saved_count}개 신규 저장")
    logger.info("="*80)


def save_to_db(products):
    """DB에 저장 (중복 제외)"""
    logger.info("\n데이터베이스 저장 중...")

    db = SessionLocal()
    saved = 0
    skipped = 0

    try:
        for product in products:
            if not product.get("isbn"):
                skipped += 1
                continue

            # 중복 체크
            existing = db.query(KyoboProduct).filter(
                KyoboProduct.isbn == product["isbn"]
            ).first()

            if existing:
                logger.debug(f"이미 존재: {product['title'][:40]}")
                skipped += 1
                continue

            # 저장
            kyobo_product = KyoboProduct(
                isbn=product["isbn"],
                title=product["title"],
                author=product["author"],
                publisher=product["publisher"],
                original_price=product["original_price"],
                category=product["category"],
                subcategory=product["subcategory"],
                image_url=product["image_url"],
                description=product["description"],
                kyobo_url=product["kyobo_url"],
                publish_date=product["publish_date"],
                crawled_at=datetime.utcnow(),
                is_processed=False
            )

            db.add(kyobo_product)
            saved += 1
            logger.info(f"저장: {product['title'][:50]}")

        db.commit()

        logger.info(f"\nDB 저장 완료: 저장 {saved}개, 건너뜀 {skipped}개")
        return saved

    except Exception as e:
        logger.error(f"DB 저장 오류: {e}")
        db.rollback()
        return 0

    finally:
        db.close()


def generate_csvs(products):
    """CSV 생성"""
    logger.info("\n쿠팡 CSV 생성 중...")

    # 계정 조회
    db = SessionLocal()
    accounts = db.query(Account).filter(Account.is_active == True).all()

    if accounts:
        account_names = [acc.account_name for acc in accounts]
    else:
        account_names = ["account_1", "account_2", "account_3", "account_4", "account_5"]

    db.close()

    # 상품 데이터 변환
    product_data = []
    for p in products:
        if not p.get("isbn"):
            continue

        sale_price = int(p["original_price"] * 0.9)
        product_data.append({
            "product_name": p["title"],
            "original_price": p["original_price"],
            "sale_price": sale_price,
            "isbn": p["isbn"],
            "publisher": p["publisher"],
            "author": p["author"],
            "main_image_url": p["image_url"],
            "description": p["description"] or "상세페이지 참조"
        })

    if not product_data:
        logger.warning("생성할 상품이 없습니다.")
        return

    # CSV 생성
    generator = CoupangCSVGenerator()
    result = generator.generate_batch_csvs(product_data, account_names)

    logger.info(f"\nCSV 생성 완료:")
    for account, filepath in result.items():
        logger.info(f"  {account}: {filepath}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"스크립트 실행 오류: {e}", exc_info=True)
        sys.exit(1)
