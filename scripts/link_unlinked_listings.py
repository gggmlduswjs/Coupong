#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
unlinked_isbns.txt의 ISBN으로 알라딘 API 조회 → books/products 생성 → listings 연결

사용법:
    python scripts/link_unlinked_listings.py [--dry-run] [--limit N]
"""

import os
import sys
import time
import argparse
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.models import Listing, Book, Product, Publisher
from crawlers.aladin_api_crawler import AladinAPICrawler
from config.publishers import get_publisher_info


def load_unlinked_isbns() -> list:
    """unlinked_isbns.txt에서 ISBN 목록 로드"""
    isbn_file = Path(__file__).parent.parent / "unlinked_isbns.txt"
    if not isbn_file.exists():
        print(f"파일 없음: {isbn_file}")
        return []

    with open(isbn_file, 'r') as f:
        return [line.strip() for line in f if line.strip()]


def main():
    parser = argparse.ArgumentParser(description="Unlinked listings 연결")
    parser.add_argument("--dry-run", action="store_true", help="실제 DB 수정 없이 시뮬레이션")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 ISBN 수 (0=전체)")
    args = parser.parse_args()

    # ISBN 로드
    isbns = load_unlinked_isbns()
    if args.limit > 0:
        isbns = isbns[:args.limit]

    print(f"처리할 ISBN: {len(isbns)}개")

    if args.dry_run:
        print("[DRY-RUN 모드]")
        return

    # DB 및 API 초기화
    db = SessionLocal()
    ttb_key = os.getenv('ALADIN_TTB_KEY', 'ttbsjrnf57490005001')
    crawler = AladinAPICrawler(ttb_key=ttb_key)

    created_books = 0
    failed_isbns = []

    for i, isbn in enumerate(isbns):
        if i % 100 == 0:
            print(f"진행: {i}/{len(isbns)} (성공: {created_books})")

        try:
            # 이미 있는지 확인
            existing = db.query(Book).filter(Book.isbn == isbn).first()
            if existing:
                continue

            # 알라딘 조회
            result = crawler.search_by_isbn(isbn)
            if not result or not result.get('item'):
                failed_isbns.append(isbn)
                continue

            item = result['item'][0]

            # Publisher 확인/생성
            pub_name = item.get('publisher', '알수없음')
            publisher = db.query(Publisher).filter(Publisher.name == pub_name).first()
            if not publisher:
                # config에서 공급율 조회, 없으면 65% 기본값
                pub_info = get_publisher_info(pub_name)
                if pub_info:
                    margin_rate = pub_info["margin"]
                    min_free_shipping = pub_info["min_free_shipping"]
                else:
                    margin_rate = 65
                    min_free_shipping = 23900
                publisher = Publisher(
                    name=pub_name,
                    margin_rate=margin_rate,
                    supply_rate=margin_rate / 100.0,
                    min_free_shipping=min_free_shipping,
                )
                db.add(publisher)
                db.flush()

            # Book 생성
            book = Book(
                isbn=isbn,
                title=item.get('title', ''),
                publisher_id=publisher.id,
                list_price=item.get('priceStandard', item.get('priceSales', 0)),
            )
            db.add(book)
            db.flush()

            # Product 생성
            product = Product(
                book_id=book.id,
                publisher_id=publisher.id,
                supply_price=int(book.list_price * 0.65) if book.list_price else 0,
                selling_price=int(book.list_price * 0.9) if book.list_price else 0,
                margin=int(book.list_price * 0.25) if book.list_price else 0,
                margin_rate=25.0,
                shipping_policy='NOT_FREE'
            )
            db.add(product)
            db.flush()

            created_books += 1
            time.sleep(0.1)  # Rate limit

        except Exception as e:
            failed_isbns.append(isbn)
            if 'UNIQUE' not in str(e):
                print(f"  오류 {isbn}: {e}")
            db.rollback()
            continue

        # 중간 커밋
        if created_books % 100 == 0:
            db.commit()

    db.commit()
    print(f"\n=== 1단계 완료 ===")
    print(f"생성: {created_books}개 books/products")
    print(f"실패: {len(failed_isbns)}개")

    # 2단계: listings 연결
    print("\n=== 2단계: listings 연결 ===")

    # Book ISBN → Product ID 매핑
    all_books = db.query(Book).all()
    isbn_to_product = {}
    for book in all_books:
        if book.isbn:
            product = db.query(Product).filter(Product.book_id == book.id).first()
            if product:
                isbn_to_product[book.isbn] = product.id

    # Unlinked listings 연결
    unlinked = db.query(Listing).filter(
        Listing.isbn.isnot(None),
        Listing.product_id.is_(None)
    ).all()

    linked = 0
    for lst in unlinked:
        if lst.isbn in isbn_to_product:
            lst.product_id = isbn_to_product[lst.isbn]
            linked += 1

    db.commit()
    print(f"연결됨: {linked}개 listings")

    # 최종 상태
    total = db.query(Listing).count()
    connected = db.query(Listing).filter(Listing.product_id.isnot(None)).count()
    print(f"\n=== 최종 상태 ===")
    print(f"products 연결: {connected}/{total} ({100*connected/total:.1f}%)")

    # 실패 목록 저장
    if failed_isbns:
        with open('failed_isbns_final.txt', 'w') as f:
            f.write('\n'.join(failed_isbns))
        print(f"실패 목록: failed_isbns_final.txt")

    db.close()


if __name__ == "__main__":
    main()
