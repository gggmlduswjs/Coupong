"""출판사 설정 및 매입률 정보

min_free_shipping: 무료배송 최소 정가 (원). 0 = 무료배송 없음.
배송비 결정 로직: app.constants.determine_customer_shipping_fee() 참조
"""

PUBLISHERS = [
    # 매입률 40% — 정가 15,000원 이상 무료배송
    {"name": "마린북스", "margin": 40, "min_free_shipping": 15000},
    {"name": "아카데미소프트", "margin": 40, "min_free_shipping": 15000},
    {"name": "렉스미디어", "margin": 40, "min_free_shipping": 15000},
    {"name": "렉스미디어닷넷", "margin": 40, "min_free_shipping": 15000},
    {"name": "아소미디어(아카데미소프트)", "margin": 40, "min_free_shipping": 15000},
    {"name": "해람북스", "margin": 40, "min_free_shipping": 15000},
    {"name": "웰북", "margin": 40, "min_free_shipping": 15000},

    # 매입률 55% — 정가 15,000원 이상 무료배송
    {"name": "크라운", "margin": 55, "min_free_shipping": 15000},
    {"name": "영진", "margin": 55, "min_free_shipping": 15000},
    {"name": "매스티안", "margin": 55, "min_free_shipping": 15000},

    # 매입률 60% — 정가 18,000원 이상 무료배송
    {"name": "소마", "margin": 60, "min_free_shipping": 18000},
    {"name": "씨투엠에듀", "margin": 60, "min_free_shipping": 18000},
    {"name": "이퓨처", "margin": 60, "min_free_shipping": 18000},
    {"name": "사회평론", "margin": 60, "min_free_shipping": 18000},
    {"name": "길벗", "margin": 60, "min_free_shipping": 18000},
    {"name": "아티오", "margin": 60, "min_free_shipping": 18000},
    {"name": "이지스퍼블리싱", "margin": 60, "min_free_shipping": 18000},
    {"name": "이지스에듀(이지스퍼블리싱)", "margin": 60, "min_free_shipping": 18000},
    {"name": "나눔 클래스", "margin": 60, "min_free_shipping": 18000},
    {"name": "나눔에이엔티", "margin": 60, "min_free_shipping": 18000},
    {"name": "배움", "margin": 60, "min_free_shipping": 18000},
    {"name": "어울림", "margin": 60, "min_free_shipping": 18000},
    {"name": "유강", "margin": 60, "min_free_shipping": 18000},
    {"name": "혜지원", "margin": 60, "min_free_shipping": 18000},
    {"name": "푸른향기", "margin": 60, "min_free_shipping": 18000},
    {"name": "디지털북스", "margin": 60, "min_free_shipping": 18000},
    {"name": "생각의집", "margin": 60, "min_free_shipping": 18000},
    {"name": "연두에디션", "margin": 60, "min_free_shipping": 18000},
    {"name": "좋은습관연구소", "margin": 60, "min_free_shipping": 18000},
    {"name": "피앤피북", "margin": 60, "min_free_shipping": 18000},
    {"name": "예림당", "margin": 60, "min_free_shipping": 18000},
    {"name": "ALIST", "margin": 60, "min_free_shipping": 18000},
    {"name": "시서례", "margin": 60, "min_free_shipping": 18000},
    {"name": "도서출판 창", "margin": 60, "min_free_shipping": 18000},
    {"name": "백만문화사", "margin": 60, "min_free_shipping": 18000},
    {"name": "풀잎", "margin": 60, "min_free_shipping": 18000},

    # 매입률 65% — 정가 20,500원 이상 무료 / 18,000~20,000 → 1,000원
    {"name": "개념원리", "margin": 65, "min_free_shipping": 20500},
    {"name": "개념원리수학연구소", "margin": 65, "min_free_shipping": 20500},
    {"name": "이투스", "margin": 65, "min_free_shipping": 20500},
    {"name": "이투스북", "margin": 65, "min_free_shipping": 20500},
    {"name": "비상교육", "margin": 65, "min_free_shipping": 20500},
    {"name": "능률교육", "margin": 65, "min_free_shipping": 20500},
    {"name": "씨투", "margin": 65, "min_free_shipping": 20500},
    {"name": "지학사", "margin": 65, "min_free_shipping": 20500},
    {"name": "수경출판사", "margin": 65, "min_free_shipping": 20500},
    {"name": "쏠티북스", "margin": 65, "min_free_shipping": 20500},
    {"name": "마더텅", "margin": 65, "min_free_shipping": 20500},
    {"name": "한빛미디어", "margin": 65, "min_free_shipping": 20500},
    {"name": "시대고시", "margin": 65, "min_free_shipping": 20500},
    {"name": "나비의 활주로", "margin": 65, "min_free_shipping": 20500},
    {"name": "푸른겨울", "margin": 65, "min_free_shipping": 20500},
    {"name": "디자인 이음", "margin": 65, "min_free_shipping": 20500},
    {"name": "이은콘텐츠 주식회사", "margin": 65, "min_free_shipping": 20500},
    {"name": "성안당", "margin": 65, "min_free_shipping": 20500},
    {"name": "지식만들기", "margin": 65, "min_free_shipping": 20500},
    {"name": "다락원", "margin": 65, "min_free_shipping": 20500},
    {"name": "에이콘", "margin": 65, "min_free_shipping": 20500},
    {"name": "기탄교육", "margin": 65, "min_free_shipping": 20500},
    {"name": "쎄듀", "margin": 65, "min_free_shipping": 20500},
    {"name": "에듀윌", "margin": 65, "min_free_shipping": 20500},
    {"name": "디딤돌", "margin": 65, "min_free_shipping": 20500},
    {"name": "꿈을담는틀", "margin": 65, "min_free_shipping": 20500},
    {"name": "미래엔에듀", "margin": 65, "min_free_shipping": 20500},
    {"name": "미래엔", "margin": 65, "min_free_shipping": 20500},
    {"name": "진학사", "margin": 65, "min_free_shipping": 20500},
    {"name": "키출판사", "margin": 65, "min_free_shipping": 20500},
    {"name": "폴리북스", "margin": 65, "min_free_shipping": 20500},
    {"name": "아름다운샘", "margin": 65, "min_free_shipping": 20500},

    # 매입률 62% — 정가 18,000원 이상 무료 / 미만 → 2,000원
    {"name": "에듀원", "margin": 62, "min_free_shipping": 18000},
    {"name": "에듀플라자", "margin": 62, "min_free_shipping": 18000},
    {"name": "베스트콜렉션", "margin": 62, "min_free_shipping": 18000},
    {"name": "내신콘서트", "margin": 62, "min_free_shipping": 18000},

    # 매입률 67% — 70% 규칙 적용 (무료배송 없음, 최선 1,000원)
    {"name": "동아", "margin": 67, "min_free_shipping": 0},

    # 매입률 70% — 무료배송 없음 (최선 1,000원)
    {"name": "좋은책신사고", "margin": 70, "min_free_shipping": 0},

    # 매입률 73% — 무료배송 없음 (조건부 60,000원)
    {"name": "한국교육방송공사", "margin": 73, "min_free_shipping": 0},
    {"name": "EBS", "margin": 73, "min_free_shipping": 0},
]


def get_publisher_names():
    """출판사 이름 리스트 반환"""
    return [p["name"] for p in PUBLISHERS]


def get_publisher_info(publisher_name: str):
    """출판사 정보 조회"""
    for p in PUBLISHERS:
        if p["name"] in publisher_name or publisher_name in p["name"]:
            return p
    return None


def is_valid_publisher(publisher_name: str):
    """취급 출판사 여부 확인"""
    return get_publisher_info(publisher_name) is not None


def calculate_profit(publisher_name: str, sale_price: int):
    """예상 수익 계산"""
    info = get_publisher_info(publisher_name)
    if not info:
        return 0

    # 매입가 = 판매가 × 공급율 / 100
    purchase_price = sale_price * info["margin"] / 100

    # 수익 = 판매가 - 매입가 - 쿠팡 수수료(11%)
    coupang_fee = sale_price * 0.11
    profit = sale_price - purchase_price - coupang_fee

    return int(profit)


def meets_free_shipping(publisher_name: str, list_price: int):
    """무료배송 기준 충족 여부 (정가 기준)"""
    from app.constants import determine_customer_shipping_fee
    info = get_publisher_info(publisher_name)
    if not info:
        return False

    return determine_customer_shipping_fee(info["margin"], list_price) == 0


if __name__ == "__main__":
    # 테스트
    print("출판사 리스트:")
    for name in get_publisher_names():
        print(f"  - {name}")

    print("\n예시: 길벗 도서 20,000원")
    info = get_publisher_info("길벗")
    print(f"  매입률: {info['margin']}%")
    print(f"  예상 수익: {calculate_profit('길벗', 20000):,}원")
    print(f"  무료배송: {meets_free_shipping('길벗', 20000)}")
