"""간단 도서 입력 시스템"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import SessionLocal
from app.models.kyobo_product import KyoboProduct
from app.models.account import Account
from uploaders.coupang_csv_generator import CoupangCSVGenerator
from datetime import datetime


def input_books():
    """대화형 도서 입력"""

    print("\n" + "="*60)
    print("도서 정보 간단 입력 시스템")
    print("="*60)
    print("\n팁: 엑셀에서 복사/붙여넣기 가능")
    print("     종료하려면 빈 칸에서 Enter\n")

    books = []

    while True:
        print(f"\n--- 도서 {len(books) + 1} ---")

        isbn = input("ISBN (13자리): ").strip()
        if not isbn:
            break

        title = input("제목: ").strip()
        if not title:
            break

        price_input = input("정가 (원): ").strip()
        try:
            price = int(price_input.replace(",", ""))
        except:
            print("가격 형식 오류. 건너뜀.")
            continue

        publisher = input("출판사 (선택): ").strip() or "기타"
        author = input("저자 (선택): ").strip() or "저자미상"

        books.append({
            "isbn": isbn,
            "title": title,
            "original_price": price,
            "publisher": publisher,
            "author": author
        })

        print(f"✓ 추가됨: {title}")

    if not books:
        print("\n입력된 도서가 없습니다.")
        return

    print(f"\n총 {len(books)}권 입력됨")

    # DB 저장
    save_to_db(books)

    # CSV 생성
    generate_csvs(books)


def save_to_db(books):
    """DB에 저장"""
    print("\n" + "="*60)
    print("데이터베이스 저장 중...")
    print("="*60)

    db = SessionLocal()
    saved = 0

    try:
        for book in books:
            # 중복 체크
            existing = db.query(KyoboProduct).filter(
                KyoboProduct.isbn == book["isbn"]
            ).first()

            if existing:
                print(f"⏭️  이미 존재: {book['title'][:40]}")
                continue

            # 저장
            product = KyoboProduct(
                isbn=book["isbn"],
                title=book["title"],
                author=book["author"],
                publisher=book["publisher"],
                original_price=book["original_price"],
                category="교재",
                crawled_at=datetime.utcnow(),
                is_processed=False
            )

            db.add(product)
            saved += 1
            print(f"✓ 저장됨: {book['title'][:40]}")

        db.commit()
        print(f"\n✅ DB 저장 완료: {saved}권")

    except Exception as e:
        print(f"❌ 오류: {e}")
        db.rollback()

    finally:
        db.close()


def generate_csvs(books):
    """CSV 생성"""
    print("\n" + "="*60)
    print("쿠팡 CSV 생성 중...")
    print("="*60)

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
    for book in books:
        sale_price = int(book["original_price"] * 0.9)
        product_data.append({
            "product_name": book["title"],
            "original_price": book["original_price"],
            "sale_price": sale_price,
            "isbn": book["isbn"],
            "publisher": book["publisher"],
            "author": book["author"],
            "main_image_url": "",
            "description": "상세페이지 참조"
        })

    # CSV 생성
    generator = CoupangCSVGenerator()
    result = generator.generate_batch_csvs(product_data, account_names)

    print("\n✅ CSV 생성 완료:")
    for account, filepath in result.items():
        print(f"   {account}: {filepath}")

    print("\n" + "="*60)
    print("완료!")
    print("="*60)
    print("\n다음 단계:")
    print("1. data/uploads/ 폴더 확인")
    print("2. 쿠팡 판매자센터 접속")
    print("3. 상품관리 > 일괄등록")
    print("4. CSV 파일 업로드")
    print()


def main():
    """메인"""
    print("\n" + "🚀 "*30)
    print("도서 간단 입력 → 쿠팡 CSV 자동 생성")
    print("🚀 "*30)

    choice = input("\n입력 방법을 선택하세요:\n1. 직접 입력\n2. CSV 파일에서 읽기\n\n선택 (1 or 2): ").strip()

    if choice == "1":
        input_books()
    elif choice == "2":
        print("\nCSV 파일 경로를 입력하세요 (예: books.csv)")
        csv_path = input("경로: ").strip()
        # TODO: CSV 읽기 기능
        print("CSV 읽기 기능은 곧 추가됩니다.")
    else:
        print("취소되었습니다.")


if __name__ == "__main__":
    main()
