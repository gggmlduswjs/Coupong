"""
raw_json에서 ISBN 재파싱 스크립트

raw_json 데이터에서 ISBN을 강화된 방식으로 추출하여 listings 테이블을 업데이트합니다.
- 모든 items 확인 (첫 번째만 X)
- attributes, externalVendorSku, barcode, searchTags 모두 검사
- ISBN-13 체크섬 검증
- API 호출 없이 즉시 실행
"""
import re
import json
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import List

# UTF-8 출력 설정 (Windows 인코딩 문제 해결)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.database import get_db


def validate_isbn13_checksum(isbn: str) -> bool:
    """ISBN-13 체크섬 검증"""
    if not isbn or len(isbn) != 13:
        return False
    if not isbn.isdigit():
        return False
    if not isbn.startswith(('978', '979')):
        return False
    try:
        check_sum = sum(
            int(isbn[i]) * (1 if i % 2 == 0 else 3)
            for i in range(12)
        )
        calculated_check = (10 - (check_sum % 10)) % 10
        return calculated_check == int(isbn[12])
    except (ValueError, IndexError):
        return False


def extract_all_isbns_from_raw_json(raw_json_str: str) -> List[str]:
    """
    raw_json에서 모든 ISBN 추출 (강화 버전)

    모든 items 순회, 모든 필드 검사, ISBN-13 체크섬 검증, 중복 제거
    """
    if not raw_json_str:
        return []

    try:
        data = json.loads(raw_json_str)
    except json.JSONDecodeError:
        return []

    isbn_pattern = re.compile(r'97[89]\d{10}')
    found_isbns = set()

    items = data.get('items', [])
    if not items:
        return []

    for item in items:
        # 1. attributes 배열에서 추출
        attributes = item.get('attributes', [])
        if isinstance(attributes, list):
            for attr in attributes:
                attr_name = attr.get('attributeTypeName', '')
                attr_value = attr.get('attributeValueName', '')

                if attr_name == 'ISBN' and attr_value:
                    if any(skip in attr_value for skip in ['상세', '참조', '해당없음', '없음']):
                        continue
                    cleaned = re.sub(r'[^0-9]', '', attr_value)
                    if validate_isbn13_checksum(cleaned):
                        found_isbns.add(cleaned)

                matches = isbn_pattern.findall(str(attr_value))
                for isbn in matches:
                    if validate_isbn13_checksum(isbn):
                        found_isbns.add(isbn)

        # 2. barcode 필드
        barcode = str(item.get('barcode', ''))
        for isbn in isbn_pattern.findall(barcode):
            if validate_isbn13_checksum(isbn):
                found_isbns.add(isbn)

        # 3. externalVendorSku
        external_sku = str(item.get('externalVendorSku', ''))
        for isbn in isbn_pattern.findall(external_sku):
            if validate_isbn13_checksum(isbn):
                found_isbns.add(isbn)

        # 4. searchTags 배열
        search_tags = item.get('searchTags', [])
        if isinstance(search_tags, list):
            for tag in search_tags:
                for isbn in isbn_pattern.findall(str(tag)):
                    if validate_isbn13_checksum(isbn):
                        found_isbns.add(isbn)

        # 5. vendorItemName
        vendor_name = str(item.get('vendorItemName', ''))
        for isbn in isbn_pattern.findall(vendor_name):
            if validate_isbn13_checksum(isbn):
                found_isbns.add(isbn)

    # 6. 최상위 레벨 필드
    product_name = str(data.get('sellerProductName', ''))
    for isbn in isbn_pattern.findall(product_name):
        if validate_isbn13_checksum(isbn):
            found_isbns.add(isbn)

    return sorted(list(found_isbns))


def backfill_isbn_from_raw_json(dry_run: bool = False, limit: int = None):
    """
    raw_json에서 ISBN을 추출하여 listings 테이블 업데이트 (PostgreSQL 전용)
    """
    db = next(get_db())

    print("=" * 80)
    print("raw_json에서 ISBN 재파싱")
    print("=" * 80)
    print(f"시작 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"모드: {'DRY RUN (미리보기)' if dry_run else 'LIVE (실제 업데이트)'}")
    if limit:
        print(f"제한: 최대 {limit}개 레코드")
    print()

    # ISBN이 없고 raw_json이 있는 listings 조회
    query = """
        SELECT id, raw_json, product_name
        FROM listings
        WHERE isbn IS NULL
          AND raw_json IS NOT NULL
          AND raw_json != ''
    """
    if limit:
        query += f" LIMIT {limit}"

    result = db.execute(text(query))
    candidates = result.fetchall()

    print(f"대상 레코드: {len(candidates):,}개")
    print()

    stats = {
        'total': len(candidates),
        'success': 0,
        'failed': 0,
        'single_isbn': 0,
        'multiple_isbn': 0,
    }

    if stats['total'] == 0:
        print("ISBN이 없는 raw_json 레코드가 없습니다.")
        return stats

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        raw_json = row[1]
        product_name = row[2]

        isbns = extract_all_isbns_from_raw_json(raw_json)

        if isbns:
            isbn_str = ','.join(isbns)
            stats['success'] += 1
            if len(isbns) == 1:
                stats['single_isbn'] += 1
            else:
                stats['multiple_isbn'] += 1
            updated_listings.append((listing_id, isbn_str, product_name))

            if idx % 100 == 0:
                print(f"  진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - 성공: {stats['success']:,}")
        else:
            stats['failed'] += 1

    print()
    print("=" * 80)
    print("추출 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"   - 단일 ISBN: {stats['single_isbn']:,}개")
    print(f"   - 복수 ISBN: {stats['multiple_isbn']:,}개 (세트 상품)")
    print(f"실패: {stats['failed']:,}개 ({stats['failed']/stats['total']*100:.1f}%)")
    print()

    # 샘플 출력
    if updated_listings:
        print("추출 샘플 (처음 10개):")
        print("-" * 80)
        for listing_id, isbn, product_name in updated_listings[:10]:
            isbn_count = len(isbn.split(','))
            isbn_type = "세트" if isbn_count > 1 else "단권"
            print(f"ID {listing_id:5d} | ISBN: {isbn[:30]:30s} | [{isbn_type}] {product_name[:40]}")
        print()

    if not dry_run:
        print("데이터베이스 업데이트 중...")
        update_count = 0

        for listing_id, isbn_str, _ in updated_listings:
            try:
                db.execute(
                    text("UPDATE listings SET isbn = :isbn WHERE id = :id"),
                    {"isbn": isbn_str, "id": listing_id}
                )
                update_count += 1

                if update_count % 100 == 0:
                    db.commit()
                    print(f"   체크포인트: {update_count:,}개 커밋됨")
            except Exception as e:
                print(f"  ID {listing_id} 업데이트 실패: {e}")
                continue

        db.commit()
        print(f"업데이트 완료: {update_count:,}개")
    else:
        print("DRY RUN 모드 - 변경사항이 저장되지 않았습니다")

    print()
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='raw_json에서 ISBN 재파싱')
    parser.add_argument('--dry-run', action='store_true', help='변경사항을 저장하지 않고 미리보기만')
    parser.add_argument('--limit', type=int, help='처리할 최대 레코드 수 (테스트용)')

    args = parser.parse_args()

    try:
        stats = backfill_isbn_from_raw_json(dry_run=args.dry_run, limit=args.limit)

        if stats['total'] > 0:
            print()
            print("최종 통계:")
            print(f"   성공률: {stats['success']/stats['total']*100:.1f}%")
            print(f"   단일 ISBN: {stats['single_isbn']:,}개")
            print(f"   복수 ISBN: {stats['multiple_isbn']:,}개")

    except Exception as e:
        print(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
