"""
Phase 1: raw_json에서 ISBN 재파싱 스크립트

raw_json 데이터에서 ISBN을 강화된 방식으로 추출하여 listings 테이블을 업데이트합니다.
- 모든 items 확인 (첫 번째만 X)
- attributes, externalVendorSku, barcode, searchTags 모두 검사
- ISBN-13 체크섬 검증
- API 호출 없이 즉시 실행 (예상: 5-10분)

예상 성과: +800~1,200 ISBN
"""
import re
import json
import sys
import io
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple

# UTF-8 출력 설정 (Windows 인코딩 문제 해결)
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from app.database import get_db
from app.models.listing import Listing


def validate_isbn13_checksum(isbn: str) -> bool:
    """
    ISBN-13 체크섬 검증

    ISBN-13은 978/979로 시작하는 13자리 숫자이며,
    마지막 자리는 체크 디지트입니다.

    검증 알고리즘:
    1. 첫 12자리의 가중치 합 계산 (홀수 자리는 1, 짝수 자리는 3)
    2. (10 - (합계 % 10)) % 10 = 체크 디지트
    """
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

    기존 _extract_isbn() 함수의 한계:
    - 첫 번째 item만 확인
    - attributes의 "해당없음" 뒤에 있는 ISBN 놓침
    - externalVendorSku 미검사

    개선사항:
    - 모든 items 순회
    - 모든 필드 철저히 검사
    - ISBN-13 체크섬 검증
    - 중복 제거

    Returns:
        검증된 ISBN 리스트 (중복 제거됨)
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
        # 1. attributes 배열에서 추출 (가장 정확)
        attributes = item.get('attributes', [])
        if isinstance(attributes, list):
            for attr in attributes:
                attr_name = attr.get('attributeTypeName', '')
                attr_value = attr.get('attributeValueName', '')

                if attr_name == 'ISBN' and attr_value:
                    # "상세페이지 참조", "해당없음" 등 제외
                    if any(skip in attr_value for skip in ['상세', '참조', '해당없음', '없음']):
                        continue

                    # 숫자만 추출
                    cleaned = re.sub(r'[^0-9]', '', attr_value)
                    if validate_isbn13_checksum(cleaned):
                        found_isbns.add(cleaned)

                # 다른 속성 값에서도 ISBN 패턴 검색
                matches = isbn_pattern.findall(str(attr_value))
                for isbn in matches:
                    if validate_isbn13_checksum(isbn):
                        found_isbns.add(isbn)

        # 2. barcode 필드
        barcode = str(item.get('barcode', ''))
        matches = isbn_pattern.findall(barcode)
        for isbn in matches:
            if validate_isbn13_checksum(isbn):
                found_isbns.add(isbn)

        # 3. externalVendorSku (기존에 누락됨!)
        external_sku = str(item.get('externalVendorSku', ''))
        matches = isbn_pattern.findall(external_sku)
        for isbn in matches:
            if validate_isbn13_checksum(isbn):
                found_isbns.add(isbn)

        # 4. searchTags 배열
        search_tags = item.get('searchTags', [])
        if isinstance(search_tags, list):
            for tag in search_tags:
                matches = isbn_pattern.findall(str(tag))
                for isbn in matches:
                    if validate_isbn13_checksum(isbn):
                        found_isbns.add(isbn)

        # 5. vendorItemName
        vendor_name = str(item.get('vendorItemName', ''))
        matches = isbn_pattern.findall(vendor_name)
        for isbn in matches:
            if validate_isbn13_checksum(isbn):
                found_isbns.add(isbn)

    # 6. 최상위 레벨 필드들도 검사
    product_name = str(data.get('sellerProductName', ''))
    matches = isbn_pattern.findall(product_name)
    for isbn in matches:
        if validate_isbn13_checksum(isbn):
            found_isbns.add(isbn)

    return sorted(list(found_isbns))


def backfill_isbn_from_raw_json(dry_run: bool = False, limit: int = None, db_path: str = None):
    """
    raw_json에서 ISBN을 추출하여 listings 테이블 업데이트

    Args:
        dry_run: True일 경우 변경사항을 커밋하지 않고 미리보기만
        limit: 처리할 최대 레코드 수 (테스트용)
        db_path: 사용할 DB 파일 경로 (기본값: 환경변수 설정)
    """
    if db_path:
        # 직접 SQLite 연결
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        db = conn
        use_raw_sqlite = True
    else:
        db = next(get_db())
        use_raw_sqlite = False

    print("=" * 80)
    print("Phase 1: raw_json에서 ISBN 재파싱")
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

    if use_raw_sqlite:
        cursor = db.cursor()
        cursor.execute(query)
        candidates = cursor.fetchall()
    else:
        result = db.execute(text(query))
        candidates = result.fetchall()

    print(f"📊 대상 레코드: {len(candidates):,}개")
    print()

    # 통계
    stats = {
        'total': len(candidates),
        'success': 0,
        'failed': 0,
        'single_isbn': 0,
        'multiple_isbn': 0,
        'invalid_isbn': 0
    }

    updated_listings = []

    for idx, row in enumerate(candidates, 1):
        listing_id = row[0]
        raw_json = row[1]
        product_name = row[2]

        # ISBN 추출
        isbns = extract_all_isbns_from_raw_json(raw_json)

        if isbns:
            isbn_str = ','.join(isbns)

            # 통계 업데이트
            stats['success'] += 1
            if len(isbns) == 1:
                stats['single_isbn'] += 1
            else:
                stats['multiple_isbn'] += 1

            updated_listings.append((listing_id, isbn_str, product_name))

            # 진행 상황 출력 (100개마다)
            if idx % 100 == 0:
                print(f"✓ 진행: {idx:,}/{len(candidates):,} ({idx/len(candidates)*100:.1f}%) - 성공: {stats['success']:,}")
        else:
            stats['failed'] += 1

    print()
    print("=" * 80)
    print("추출 결과")
    print("=" * 80)
    print(f"총 처리: {stats['total']:,}개")
    print(f"✅ 성공: {stats['success']:,}개 ({stats['success']/stats['total']*100:.1f}%)")
    print(f"   - 단일 ISBN: {stats['single_isbn']:,}개")
    print(f"   - 복수 ISBN: {stats['multiple_isbn']:,}개 (세트 상품)")
    print(f"❌ 실패: {stats['failed']:,}개 ({stats['failed']/stats['total']*100:.1f}%)")
    print()

    # 샘플 출력 (처음 10개)
    if updated_listings:
        print("📝 추출 샘플 (처음 10개):")
        print("-" * 80)
        for listing_id, isbn, product_name in updated_listings[:10]:
            isbn_count = len(isbn.split(','))
            isbn_type = "세트" if isbn_count > 1 else "단권"
            print(f"ID {listing_id:5d} | ISBN: {isbn[:30]:30s} | [{isbn_type}] {product_name[:40]}")
        print()

    if not dry_run:
        # 실제 업데이트 수행
        print("💾 데이터베이스 업데이트 중...")

        update_count = 0
        duplicate_count = 0

        for listing_id, isbn_str, _ in updated_listings:
            try:
                if use_raw_sqlite:
                    cursor = db.cursor()

                    # 중복 체크: 같은 account_id에 같은 ISBN이 이미 있는지 확인
                    cursor.execute("""
                        SELECT account_id FROM listings WHERE id = ?
                    """, (listing_id,))
                    row = cursor.fetchone()
                    if not row:
                        continue

                    account_id = row[0]

                    # 같은 계정에 같은 ISBN이 이미 있는지 확인
                    cursor.execute("""
                        SELECT COUNT(*) FROM listings
                        WHERE account_id = ? AND isbn = ? AND id != ?
                    """, (account_id, isbn_str, listing_id))

                    if cursor.fetchone()[0] > 0:
                        # 중복이므로 스킵
                        duplicate_count += 1
                        continue

                    # 업데이트 수행
                    cursor.execute("UPDATE listings SET isbn = ? WHERE id = ?", (isbn_str, listing_id))
                else:
                    db.execute(
                        text("UPDATE listings SET isbn = :isbn WHERE id = :id"),
                        {"isbn": isbn_str, "id": listing_id}
                    )
                update_count += 1

                # 100개마다 커밋 (체크포인트)
                if update_count % 100 == 0:
                    db.commit()
                    print(f"   체크포인트: {update_count:,}개 커밋됨 (중복 스킵: {duplicate_count:,})")
            except Exception as e:
                if "UNIQUE constraint" not in str(e):
                    print(f"⚠️  ID {listing_id} 업데이트 실패: {e}")
                else:
                    duplicate_count += 1
                continue

        # 최종 커밋
        db.commit()
        print(f"✅ 업데이트 완료: {update_count:,}개")
        if duplicate_count > 0:
            print(f"⚠️  중복으로 스킵: {duplicate_count:,}개 (같은 계정에 같은 ISBN 이미 존재)")
    else:
        print("⚠️  DRY RUN 모드 - 변경사항이 저장되지 않았습니다")

    print()
    print(f"종료 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80)

    return stats


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='raw_json에서 ISBN 재파싱')
    parser.add_argument('--dry-run', action='store_true', help='변경사항을 저장하지 않고 미리보기만')
    parser.add_argument('--limit', type=int, help='처리할 최대 레코드 수 (테스트용)')
    parser.add_argument('--db', type=str, help='사용할 DB 파일 경로 (기본값: coupang_auto_backup.db)')

    args = parser.parse_args()

    # 기본값으로 backup DB 사용
    db_path = args.db or 'coupang_auto_backup.db'

    try:
        stats = backfill_isbn_from_raw_json(dry_run=args.dry_run, limit=args.limit, db_path=db_path)

        print()
        print("📊 최종 통계:")
        print(f"   성공률: {stats['success']/stats['total']*100:.1f}%")
        print(f"   단일 ISBN: {stats['single_isbn']:,}개")
        print(f"   복수 ISBN: {stats['multiple_isbn']:,}개")

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
