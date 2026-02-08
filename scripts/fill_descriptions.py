"""
상품설명 일괄 채우기
====================
판매중(active) 리스팅에 연결된 도서 중 description이 없는 것을
1차: 알라딘 API, 2차: 템플릿 자동 생성으로 채움

사용법:
    python scripts/fill_descriptions.py                    # 알라딘 API
    python scripts/fill_descriptions.py --generate         # 템플릿 자동 생성 (API 없는 것)
    python scripts/fill_descriptions.py --limit 10         # 10개만 테스트
    python scripts/fill_descriptions.py --dry-run          # 실제 저장 안 함
"""
import sys
import os
import re
import time
import argparse
import logging
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import text
from app.database import engine, init_db
from crawlers.aladin_api_crawler import AladinAPICrawler

logging.basicConfig(level=logging.INFO, format='[%(asctime)s] %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger(__name__)


def _classify_book(title, publisher):
    """제목+출판사로 도서 유형 분류"""
    t = title or ""
    p = publisher or ""
    if any(k in t for k in ['독서평설', '월간', 'DBR', '매거진', 'Vol.']):
        return 'magazine'
    if '세트' in t or 'SET' in t.upper():
        return 'set'
    if any(k in t for k in ['RPM', '개념원리', '풍산자', '쎈', '올림포스', '라이트쎈']):
        return 'math_workbook'
    if any(k in t for k in ['자이스토리', 'Xistory']):
        return 'workbook'
    if any(k in t for k in ['스마트올', '히어로', '라이트쎈']):
        return 'workbook'
    if any(k in t for k in ['ITQ', 'DIAT', '컴퓨터활용', '파워포인트', '한컴', '엑셀', '워드']):
        return 'it_cert'
    if any(k in t for k in ['검정고시', 'NCS', '공무원', '자격증']):
        return 'exam_prep'
    if any(k in t for k in ['초등', '중등', '중학', '고등', '교과서', '교육과정']):
        return 'textbook'
    if any(k in t for k in ['1일 1장', '1일1장', '워크북', '학습지']):
        return 'drill'
    return 'general'


def _extract_year(title):
    """제목에서 연도 추출"""
    m = re.search(r'(20\d{2})(?:년|학년도)?', title or "")
    return m.group(1) if m else None


def _extract_grade(title):
    """제목에서 학년/학기 추출"""
    m = re.search(r'(\d-[12]|\d학년)', title or "")
    return m.group(1) if m else None


def generate_description(title, author, publisher, list_price, category_type):
    """카테고리별 템플릿으로 상품 설명 자동 생성"""
    t = title or ""
    a = author or ""
    p = publisher or ""
    year = _extract_year(t) or ""
    grade = _extract_grade(t)

    # 공통 접미사
    suffix = f" {p} 출판." if p else ""

    if category_type == 'magazine':
        return f"{t}. 최신 트렌드와 깊이 있는 콘텐츠를 담은 정기간행물입니다.{suffix}"

    if category_type == 'set':
        # 세트 구성 수 추출
        m = re.search(r'(\d+)권', t)
        vol = f" 총 {m.group(1)}권 구성." if m else ""
        return f"{t}.{vol} 세트 구매로 체계적인 학습이 가능합니다.{suffix}"

    if category_type == 'math_workbook':
        yr = f" {year}년" if year else ""
        gr = f" {grade}" if grade else ""
        return f"{t}.{yr} 개정 교육과정 반영{gr} 수학 문제집입니다. 유형별 문제풀이로 수학 실력을 완성합니다.{suffix}"

    if category_type == 'workbook':
        yr = f" {year}년" if year else ""
        return f"{t}.{yr} 개정 교육과정 반영 문제집입니다. 핵심 개념 정리와 다양한 유형의 문제로 실력을 키웁니다.{suffix}"

    if category_type == 'it_cert':
        return f"{t}. 최신 출제 경향을 반영한 IT 자격증 수험서입니다. 이론 설명과 실전 문제로 합격을 준비합니다.{suffix}"

    if category_type == 'exam_prep':
        return f"{t}. 최신 출제 기준에 맞춘 수험서입니다. 핵심 이론 정리와 기출문제 풀이를 수록하였습니다.{suffix}"

    if category_type == 'textbook':
        yr = f" {year}년" if year else ""
        gr = f" {grade}" if grade else ""
        return f"{t}.{yr} 개정 교육과정{gr} 교재입니다. 교과 내용을 충실히 반영하여 학습 효과를 높입니다.{suffix}"

    if category_type == 'drill':
        return f"{t}. 매일 꾸준한 학습 습관을 기르는 학습지입니다. 하루 한 장으로 기초 실력을 탄탄하게 다집니다.{suffix}"

    # general
    author_part = f" {a} 저." if a else ""
    return f"{t}.{author_part} {suffix}".strip()


def fill_from_aladin(limit=0, dry_run=False):
    """1차: 알라딘 API로 설명 채우기"""
    ttb_key = os.getenv("ALADIN_TTB_KEY")
    if not ttb_key:
        logger.error("ALADIN_TTB_KEY가 .env에 없습니다.")
        return

    crawler = AladinAPICrawler(ttb_key=ttb_key)

    with engine.connect() as conn:
        query = """
            SELECT DISTINCT b.id, b.isbn, b.title
            FROM listings l
            JOIN products p ON l.product_id = p.id
            JOIN books b ON p.book_id = b.id
            WHERE l.coupang_status = 'active'
            AND (b.description IS NULL OR b.description = '')
            AND b.isbn IS NOT NULL AND b.isbn != ''
            ORDER BY b.id
        """
        if limit > 0:
            query += f" LIMIT {limit}"

        rows = conn.execute(text(query)).fetchall()
        total = len(rows)

        if total == 0:
            logger.info("채울 도서가 없습니다.")
            return

        logger.info(f"설명 누락 도서: {total}권 (알라딘 API 조회 시작)")
        if dry_run:
            logger.info("** DRY RUN 모드 **")

        filled = 0
        skipped = 0
        start = time.time()

        for i, row in enumerate(rows):
            book_id, isbn, title = row
            short_title = (title or "")[:40]

            try:
                product = crawler.search_by_isbn(isbn)
                if product and product.get("description"):
                    desc = product["description"].strip()
                    if not dry_run:
                        conn.execute(
                            text("UPDATE books SET description = :desc WHERE id = :id"),
                            {"desc": desc, "id": book_id}
                        )
                        if (filled + 1) % 20 == 0:
                            conn.commit()
                    filled += 1
                    logger.info(f"  [{i+1}/{total}] API: {short_title} ({len(desc)}자)")
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1
                logger.error(f"  [{i+1}/{total}] 오류: {short_title} - {e}")

            time.sleep(1)

        if not dry_run:
            conn.commit()

        elapsed = time.time() - start
        logger.info(f"알라딘 완료: 채움 {filled}, 스킵 {skipped} ({elapsed:.0f}초)")


def fill_from_template(limit=0, dry_run=False):
    """2차: 템플릿으로 설명 자동 생성"""
    with engine.connect() as conn:
        query = """
            SELECT DISTINCT b.id, b.isbn, b.title, b.author,
              b.publisher_name, b.list_price
            FROM listings l
            JOIN products p ON l.product_id = p.id
            JOIN books b ON p.book_id = b.id
            WHERE l.coupang_status = 'active'
            AND (b.description IS NULL OR b.description = '')
            ORDER BY b.id
        """
        if limit > 0:
            query += f" LIMIT {limit}"

        rows = conn.execute(text(query)).fetchall()
        total = len(rows)

        if total == 0:
            logger.info("채울 도서가 없습니다.")
            return

        logger.info(f"설명 누락 도서: {total}권 (템플릿 자동 생성)")
        if dry_run:
            logger.info("** DRY RUN 모드 **")

        filled = 0

        for i, row in enumerate(rows):
            book_id, isbn, title, author, publisher, list_price = row
            short_title = (title or "")[:40]

            cat_type = _classify_book(title, publisher)
            desc = generate_description(title, author, publisher, list_price, cat_type)

            if not dry_run:
                conn.execute(
                    text("UPDATE books SET description = :desc WHERE id = :id"),
                    {"desc": desc, "id": book_id}
                )
            filled += 1
            logger.info(f"  [{i+1}/{total}] {cat_type}: {short_title} → {desc[:50]}...")

        if not dry_run:
            conn.commit()

        logger.info(f"템플릿 완료: {filled}권 생성")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="상품설명 일괄 채우기")
    parser.add_argument("--generate", action="store_true", help="템플릿 자동 생성 (알라딘 없는 것)")
    parser.add_argument("--limit", type=int, default=0, help="최대 처리 수")
    parser.add_argument("--dry-run", action="store_true", help="실제 저장 안 함")
    args = parser.parse_args()

    init_db()

    if args.generate:
        fill_from_template(limit=args.limit, dry_run=args.dry_run)
    else:
        fill_from_aladin(limit=args.limit, dry_run=args.dry_run)
