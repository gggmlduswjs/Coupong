# 완전 자동화 로깅 예시
# 이 파일을 실행하면 Obsidian에 자동으로 기록됩니다!

import time
from auto_logger import auto_log, log_execution, task_context


# ============================================
# 예시 1: 간단한 함수 데코레이터
# ============================================

@auto_log("feature", "마진 계산 기능")
def calculate_margin(price: int, rate: float) -> int:
    """출판사별 마진 계산"""
    time.sleep(0.1)  # 작업 시뮬레이션
    sale_price = int(price * 0.9)
    supply_cost = int(price * rate)
    coupang_fee = int(sale_price * 0.11)
    margin = sale_price - supply_cost - coupang_fee
    return margin - 2000


# ============================================
# 예시 2: 상세 로깅 (인자 + 결과)
# ============================================

@log_execution("상세 마진 분석", log_args=True, log_result=True)
def analyze_margin_detailed(price: int, rate: float, shipping: int = 2000) -> dict:
    """마진 상세 분석 및 수익성 판단"""
    time.sleep(0.15)  # 작업 시뮬레이션

    sale_price = int(price * 0.9)
    supply_cost = int(price * rate)
    coupang_fee = int(sale_price * 0.11)
    margin = sale_price - supply_cost - coupang_fee
    net_margin = margin - shipping

    # 수익성 판단
    if net_margin >= 2000:
        profitability = "excellent"
        shipping_policy = "free"
    elif net_margin >= 0:
        profitability = "good"
        shipping_policy = "paid"
    else:
        profitability = "poor"
        shipping_policy = "bundle_required"

    return {
        "list_price": price,
        "sale_price": sale_price,
        "supply_cost": supply_cost,
        "coupang_fee": coupang_fee,
        "margin": margin,
        "net_margin": net_margin,
        "profitability": profitability,
        "shipping_policy": shipping_policy
    }


# ============================================
# 예시 3: 에러 처리
# ============================================

@auto_log("debug", "위험한 작업")
def risky_function(value: int) -> int:
    """0으로 나누기 시도"""
    if value == 0:
        raise ValueError("0으로 나눌 수 없습니다!")
    return 100 // value


# ============================================
# 예시 4: 작업 블록 (단순)
# ============================================

def simple_task():
    """간단한 작업 블록"""
    with task_context("도서 검색", "알라딘 API 검색 시뮬레이션"):
        print("  - 알라딘 API 호출 중...")
        time.sleep(0.3)
        print("  - 100권 검색 완료")


# ============================================
# 예시 5: 작업 블록 (중첩)
# ============================================

def complex_workflow():
    """복잡한 워크플로우 (여러 단계)"""

    with task_context("전체 워크플로우", "검색 → 분석 → CSV 생성"):

        # 1단계: 검색
        with task_context("1단계: 도서 검색", "알라딘 API 검색"):
            print("  [1/3] 도서 검색 중...")
            time.sleep(0.2)
            books = ["Book1", "Book2", "Book3"]
            print(f"  검색 완료: {len(books)}권")

        # 2단계: 분석
        with task_context("2단계: 마진 분석", "수익성 분석"):
            print("  [2/3] 마진 분석 중...")
            time.sleep(0.2)
            profitable = [b for b in books if "Book" in b]
            print(f"  분석 완료: {len(profitable)}권 수익 가능")

        # 3단계: CSV
        with task_context("3단계: CSV 생성", "계정별 CSV 파일 생성"):
            print("  [3/3] CSV 생성 중...")
            time.sleep(0.2)
            print("  CSV 생성 완료: 5개 파일")


# ============================================
# 예시 6: 에러가 있는 작업 블록
# ============================================

def task_with_error():
    """에러가 발생하는 작업"""
    try:
        with task_context("에러 발생 작업", "실패 시뮬레이션"):
            print("  작업 시작...")
            time.sleep(0.1)
            raise RuntimeError("의도적인 에러!")
    except RuntimeError as e:
        print(f"  에러 처리됨: {e}")


# ============================================
# 메인 실행
# ============================================

def main():
    """메인 함수 - 모든 예시 실행"""
    print("=" * 60)
    print("완전 자동화 로깅 예시 실행")
    print("=" * 60)
    print()

    # 예시 1: 간단한 함수
    print("[예시 1] 간단한 함수 자동 기록")
    result1 = calculate_margin(15000, 0.35)
    print(f"   결과: 순마진 {result1:,}원")
    print()

    # 예시 2: 상세 로깅
    print("[예시 2] 상세 로깅 (인자 + 결과)")
    result2 = analyze_margin_detailed(15000, 0.35, 2000)
    print(f"   결과: {result2['profitability']} - {result2['shipping_policy']}")
    print()

    # 예시 3: 에러 처리
    print("[예시 3] 에러 자동 기록")
    try:
        risky_function(0)
    except ValueError as e:
        print(f"   에러 발생: {e}")
    print()

    # 예시 4: 작업 블록 (단순)
    print("[예시 4] 작업 블록 자동 기록")
    simple_task()
    print()

    # 예시 5: 작업 블록 (중첩)
    print("[예시 5] 중첩 작업 블록")
    complex_workflow()
    print()

    # 예시 6: 에러가 있는 작업
    print("[예시 6] 에러가 있는 작업 블록")
    task_with_error()
    print()

    # 완료
    print("=" * 60)
    print("[OK] 모든 작업 완료!")
    print("=" * 60)
    print()
    print("[INFO] Obsidian 확인:")
    print("   obsidian_vault/01-Daily/[오늘 날짜].md")
    print()
    print("기록된 내용:")
    print("  - calculate_margin 실행 (0.1초)")
    print("  - analyze_margin_detailed 실행 (0.15초, 인자+결과)")
    print("  - risky_function 실행 실패 (ValueError)")
    print("  - 도서 검색 (0.3초)")
    print("  - 전체 워크플로우 (0.6초)")
    print("    - 1단계: 도서 검색 (0.2초)")
    print("    - 2단계: 마진 분석 (0.2초)")
    print("    - 3단계: CSV 생성 (0.2초)")
    print("  - 에러 발생 작업 (실패)")
    print()
    print("[SUCCESS] 완전 자동화 로깅 시스템 작동 중!")


if __name__ == "__main__":
    main()
