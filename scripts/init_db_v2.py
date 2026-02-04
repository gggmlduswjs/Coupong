"""데이터베이스 V2 초기화 스크립트"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.database import engine, SessionLocal, Base
from app.models import Publisher, Book, Product, BundleSKU, Listing, Account, Sales, AnalysisResult, Task


def init_database():
    """데이터베이스 테이블 생성"""
    print("\n" + "="*60)
    print("데이터베이스 V2 초기화")
    print("="*60)

    print("\n1. 테이블 생성 중...")

    # 모든 테이블 생성
    Base.metadata.create_all(bind=engine)

    print("   [OK] 테이블 생성 완료")
    print("      - accounts")
    print("      - publishers [신규]")
    print("      - books [신규] (구 kyobo_products)")
    print("      - products [개선]")
    print("      - bundle_skus [신규]")
    print("      - listings [개선]")
    print("      - sales")
    print("      - analysis_results")
    print("      - tasks")


def init_publishers():
    """출판사 데이터 초기화"""
    print("\n2. 출판사 데이터 초기화 중...")

    db = SessionLocal()

    try:
        # 기존 데이터 확인
        existing_count = db.query(Publisher).count()
        if existing_count > 0:
            print(f"   ⚠️  이미 {existing_count}개의 출판사가 등록되어 있습니다.")
            overwrite = input("   기존 데이터를 삭제하고 다시 입력할까요? (y/n): ").strip().lower()
            if overwrite == 'y':
                db.query(Publisher).delete()
                db.commit()
                print("   ✓ 기존 데이터 삭제 완료")
            else:
                print("   건너뜀")
                return

        # 출판사 데이터 (24개)
        publishers_data = [
            # 매입률 40% (공급률 60%)
            ("마린북스", 40, 9000, 0.60),
            ("아카데미소프트", 40, 9000, 0.60),
            ("렉스미디어", 40, 9000, 0.60),
            ("해람북스", 40, 9000, 0.60),

            # 매입률 55% (공급률 45%)
            ("크라운", 55, 14400, 0.45),
            ("영진", 55, 14400, 0.45),

            # 매입률 60% (공급률 40%)
            ("이퓨쳐", 60, 18000, 0.40),
            ("사회평론", 60, 18000, 0.40),
            ("길벗", 60, 18000, 0.40),
            ("아티오", 60, 18000, 0.40),
            ("이지스퍼블리싱", 60, 18000, 0.40),

            # 매입률 65% (공급률 35%)
            ("개념원리", 65, 23900, 0.35),
            ("이투스", 65, 23900, 0.35),
            ("비상교육", 65, 23900, 0.35),
            ("능률교육", 65, 23900, 0.35),
            ("씨톡", 65, 23900, 0.35),
            ("지학사", 65, 23900, 0.35),
            ("수경출판사", 65, 23900, 0.35),
            ("쏠티북스", 65, 23900, 0.35),
            ("마더텅", 65, 23900, 0.35),
            ("한빛미디어", 65, 23900, 0.35),

            # 매입률 67% (공급률 33%)
            ("동아", 67, 27600, 0.33),

            # 매입률 70% (공급률 30%)
            ("좋은책신사고", 70, 35800, 0.30),

            # 매입률 73% (공급률 27%)
            ("EBS", 73, 50800, 0.27),
            ("한국교육방송공사", 73, 50800, 0.27),
        ]

        for name, margin_rate, min_free_shipping, supply_rate in publishers_data:
            publisher = Publisher(
                name=name,
                margin_rate=margin_rate,
                min_free_shipping=min_free_shipping,
                supply_rate=supply_rate,
                is_active=True
            )
            db.add(publisher)
            print(f"   ✓ {name} (매입률 {margin_rate}%, 공급률 {int(supply_rate*100)}%)")

        db.commit()

        print(f"\n   ✅ 출판사 {len(publishers_data)}개 등록 완료")

    except Exception as e:
        print(f"\n   ❌ 오류: {e}")
        db.rollback()

    finally:
        db.close()


def test_publisher_calculations():
    """출판사 마진 계산 테스트"""
    print("\n3. 출판사 마진 계산 테스트...")

    db = SessionLocal()

    try:
        # 테스트 케이스
        test_cases = [
            ("개념원리", 15000, "65% 출판사"),
            ("길벗", 30000, "60% 출판사"),
            ("EBS", 10000, "73% 출판사 (묶음 필요)"),
        ]

        for pub_name, list_price, desc in test_cases:
            publisher = db.query(Publisher).filter(Publisher.name == pub_name).first()

            if publisher:
                margin_info = publisher.calculate_margin(list_price)
                policy = publisher.determine_shipping_policy(list_price)

                print(f"\n   [{desc}] {pub_name} - 정가 {list_price:,}원")
                print(f"      판매가: {margin_info['sale_price']:,}원")
                print(f"      공급가: {margin_info['supply_cost']:,}원")
                print(f"      쿠팡수수료: {margin_info['coupang_fee']:,}원")
                print(f"      권당 마진: {margin_info['margin_per_unit']:,}원")
                print(f"      순마진: {margin_info['net_margin']:,}원")
                print(f"      배송정책: {policy}")

        print("\n   ✅ 마진 계산 정상 작동")

    except Exception as e:
        print(f"\n   ❌ 오류: {e}")

    finally:
        db.close()


def main():
    """메인 함수"""
    print("\n" + "="*60)
    print("데이터베이스 V2 스키마 초기화")
    print("="*60)

    # 1. 테이블 생성
    init_database()

    # 2. 출판사 데이터 초기화
    init_publishers()

    # 3. 테스트
    test_publisher_calculations()

    print("\n" + "="*60)
    print("초기화 완료!")
    print("="*60)

    print("\n다음 단계:")
    print("1. python scripts/register_accounts.py (계정 등록)")
    print("2. python scripts/auto_search_publishers.py (도서 검색)")
    print()


if __name__ == "__main__":
    main()
