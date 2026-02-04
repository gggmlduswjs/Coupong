"""출판사 설정 및 매입률 정보"""

PUBLISHERS = [
    # 매입률 40%
    {"name": "마린북스", "margin": 40, "min_free_shipping": 9000},
    {"name": "아카데미소프트", "margin": 40, "min_free_shipping": 9000},
    {"name": "렉스미디어", "margin": 40, "min_free_shipping": 9000},
    {"name": "해람북스", "margin": 40, "min_free_shipping": 9000},

    # 매입률 55%
    {"name": "크라운", "margin": 55, "min_free_shipping": 14400},
    {"name": "영진", "margin": 55, "min_free_shipping": 14400},

    # 매입률 60%
    {"name": "이퓨쳐", "margin": 60, "min_free_shipping": 18000},
    {"name": "사회평론", "margin": 60, "min_free_shipping": 18000},
    {"name": "길벗", "margin": 60, "min_free_shipping": 18000},
    {"name": "아티오", "margin": 60, "min_free_shipping": 18000},
    {"name": "이지스퍼블리싱", "margin": 60, "min_free_shipping": 18000},

    # 매입률 65%
    {"name": "개념원리", "margin": 65, "min_free_shipping": 23900},
    {"name": "이투스", "margin": 65, "min_free_shipping": 23900},
    {"name": "비상교육", "margin": 65, "min_free_shipping": 23900},
    {"name": "능률교육", "margin": 65, "min_free_shipping": 23900},
    {"name": "씨톡", "margin": 65, "min_free_shipping": 23900},
    {"name": "지학사", "margin": 65, "min_free_shipping": 23900},
    {"name": "수경출판사", "margin": 65, "min_free_shipping": 23900},
    {"name": "쏠티북스", "margin": 65, "min_free_shipping": 23900},
    {"name": "마더텅", "margin": 65, "min_free_shipping": 23900},
    {"name": "한빛미디어", "margin": 65, "min_free_shipping": 23900},

    # 매입률 67%
    {"name": "동아", "margin": 67, "min_free_shipping": 27600},

    # 매입률 70%
    {"name": "좋은책신사고", "margin": 70, "min_free_shipping": 35800},

    # 매입률 73%
    {"name": "한국교육방송공사", "margin": 73, "min_free_shipping": 50800},
    {"name": "EBS", "margin": 73, "min_free_shipping": 50800},  # 한국교육방송공사 별칭
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

    # 매입가 = 판매가 × (100 - 매입률) / 100
    purchase_price = sale_price * (100 - info["margin"]) / 100

    # 수익 = 판매가 - 매입가 - 쿠팡 수수료(10%)
    coupang_fee = sale_price * 0.10
    profit = sale_price - purchase_price - coupang_fee

    return int(profit)


def meets_free_shipping(publisher_name: str, sale_price: int):
    """무료배송 기준 충족 여부"""
    info = get_publisher_info(publisher_name)
    if not info:
        return False

    return sale_price >= info["min_free_shipping"]


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
