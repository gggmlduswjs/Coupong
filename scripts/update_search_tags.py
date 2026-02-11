"""
검색 태그 일괄 업데이트 스크립트
=================================
쿠팡 셀러 인사이트 1등 상품(완자 화학)의 검색어 패턴 분석 결과를 기반으로
모든 등록 상품의 searchTags를 최적화.

패턴 예시 (완자 화학):
  완자 화학1 / 완자화학1 / 완자 고등 화학 / 완자고등화학
  고2 화학 / 고2화학 / 화학 완자 / 고2 화학 완자
  완자 고2 화학 / 완자 화학 2026 / 고2 과학 문제집

사용법:
  # 드라이런 (변경 없이 미리보기)
  python scripts/update_search_tags.py --dry-run --limit 5

  # 특정 계정만
  python scripts/update_search_tags.py --account 007-book --limit 10

  # 전체 실행
  python scripts/update_search_tags.py
"""
import argparse
import json
import logging
import re
import sys
import time
from typing import Dict, List, Optional, Tuple

# 프로젝트 루트 경로 추가
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.listing import Listing
from app.models.book import Book
from app.models.account import Account
from app.api.coupang_wing_client import CoupangWingClient, CoupangWingError
from uploaders.coupang_api_uploader import _dedupe_attributes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─── 검색어 생성에 사용할 상수 ─────────────────────────────────────

# 알려진 시리즈/브랜드명 (긴 것부터 매칭)
KNOWN_SERIES = [
    # 4글자 이상
    "수학의정석", "수학의바이블", "자이스토리", "개념원리", "라이트쎈",
    "개념쎈", "큐브수학", "마더텅", "마플교과서", "스마트파닉스",
    "내신콘서트", "기출픽", "수능완성", "수능특강",
    "블랙라벨", "풍산자", "올림포스", "이것이",
    "워드마스터", "리딩튜터", "그래머존", "능률보카", "보카바이블",
    # 3글자
    "시나공", "우공비",
    # 2글자
    "완자", "쎈", "마플", "오투", "한끝", "캡컷", "해법", "RPM",
]

# 과목 → 상위 과목 매핑
SUBJECT_MAP = {
    # 과학 계열
    "생명과학": "과학", "지구과학": "과학", "화학": "과학", "물리": "과학",
    "생물": "과학",
    # 수학 계열
    "미적분": "수학", "확률과통계": "수학", "기하": "수학",
    "공통수학": "수학", "공통수학1": "수학", "공통수학2": "수학",
    # 국어 계열
    "독해": "국어", "문법": "국어", "어휘": "국어", "독서": "국어",
    "문학": "국어", "언어와매체": "국어", "화법과작문": "국어",
    # 사회 계열
    "한국사": "사회", "세계사": "사회", "한국지리": "사회", "세계지리": "사회",
    "경제": "사회", "정치와법": "사회", "사회문화": "사회",
    "윤리와사상": "사회", "생활과윤리": "사회",
    # 영어 계열
    "영문법": "영어", "영독해": "영어", "영단어": "영어",
    "파닉스": "영어", "phonics": "영어",
    # 기본 과목 (상위 없음)
    "수학": None, "국어": None, "영어": None, "과학": None, "사회": None,
}

# 학교급 관련 태그
GRADE_LEVEL_TAGS = {
    "초등": ["초등", "초등학생", "초등교재"],
    "중학": ["중학", "중학생", "중학교"],
    "중등": ["중학", "중학생", "중등"],
    "고등": ["고등", "고등학생", "고등교재"],
}

# 교재 유형 키워드
MATERIAL_TYPES = [
    "문제집", "참고서", "기출", "모의고사", "워크북", "세트",
    "개념서", "유형서", "실전", "특강", "총정리",
]

# ─── 자격증/IT 약어 매핑 (Google 자동완성 기반) ─────────────────
CERT_ABBREVIATIONS = {
    "컴퓨터활용능력": ["컴활"],
    "컴퓨터활용": ["컴활"],
    "정보처리기사": ["정처기"],
    "정보처리기능사": ["정처기능사", "정보기"],
    "정보처리산업기사": ["정처산기"],
    "워드프로세서": ["워드", "워프"],
    "한식조리기능사": ["한식조리"],
    "양식조리기능사": ["양식조리"],
    "요양보호사": ["요양보호"],
    "빅데이터분석기사": ["빅분기"],
    "네트워크관리사": ["네관사"],
    "사무자동화산업기사": ["사무자동화"],
    "컴퓨터그래픽기능사": ["컴그"],
    "정보보안기사": ["정보보안"],
    "정보통신기사": ["정통기"],
    "직업상담사": ["직상"],
}

# 자격증 검색 패턴 (등급+필기/실기 조합)
CERT_LEVELS = ["1급", "2급", "3급"]
CERT_TYPES = ["필기", "실기"]

# 시리즈별 인기 검색어 보강 (Google 자동완성 기반)
SERIES_BOOST_TAGS = {
    "개념원리": ["개념원리 rpm", "알피엠"],
    "마더텅": ["마더텅 빨간책", "마더텅 영어듣기"],
    "시나공": ["시나공 퀵이지"],
    "빠작": ["빠작 비문학", "빠작 문법"],
    "디딤돌": ["디딤돌 수학"],
    "소마셈": ["소마셈 단계"],
    "풍산자": ["풍산자 반복수학"],
    "캡컷": ["캡컷 사용법", "영상 편집"],
}

# IT/코딩 교재 키워드
IT_KEYWORDS = {
    "엑셀": ["엑셀", "Excel", "스프레드시트"],
    "파워포인트": ["파워포인트", "PPT", "프레젠테이션"],
    "한글": ["한글", "한컴", "워드프로세서"],
    "한셀": ["한셀", "스프레드시트"],
    "한쇼": ["한쇼", "프레젠테이션"],
    "엔트리": ["엔트리", "코딩", "블록코딩"],
    "스크래치": ["스크래치", "코딩", "블록코딩"],
    "파이썬": ["파이썬", "Python", "코딩"],
    "포토샵": ["포토샵", "Photoshop"],
    "GTQ": ["GTQ", "그래픽기술자격"],
    "ITQ": ["ITQ", "정보기술자격"],
    "DIAT": ["DIAT", "디지털정보활용"],
    "코딩": ["코딩", "프로그래밍"],
}

# 검색태그 특수문자 제거 패턴
_TAG_STRIP_RE = re.compile(r'[^\w\s!@#$%^&*\-+;:\'.]+', re.UNICODE)


def extract_components(product_name: str,
                       publisher: str = "",
                       author: str = "",
                       category: str = "") -> Dict:
    """
    상품명에서 검색어 생성에 필요한 구성요소 추출

    Returns:
        {
            series: str,        # 시리즈/브랜드명 (완자, 쎈, ...)
            subject: str,       # 과목 (화학, 수학, ...)
            broader_subject: str, # 상위 과목 (과학, 수학, ...)
            grade_level: str,   # 학교급 (고등, 중학, 초등)
            grade_num: str,     # 학년 번호 (1, 2, 3)
            grade_tag: str,     # 학년 태그 (고2, 중1, ...)
            year: str,          # 연도 (2026)
            publisher: str,     # 출판사
            author: str,        # 저자
            title_words: list,  # 제목 핵심 단어들
            material_type: str, # 교재 유형 (문제집, 기출, ...)
            subject_detail: str, # 세부 과목명 (공통수학1, 확률과통계 등)
        }
    """
    title = product_name or ""

    # 제목 정규화 (특수문자 → 공백 없이 연결)
    # "사회·문화" → "사회문화", "한식ㆍ양식" → "한식양식"
    title_normalized = re.sub(r'[·‧・ㆍ]', '', title)

    # ── 시리즈명 추출 ──
    series = None
    for s in KNOWN_SERIES:
        if s in title:
            series = s
            break
    # 시리즈 못 찾으면 출판사명이 제목에 있는지 확인
    if not series and publisher and publisher in title:
        series = publisher

    # ── 과목 추출 (긴 것부터 매칭, 정규화된 제목에서도 시도) ──
    subject = None
    broader_subject = None
    subject_detail = None
    sorted_subjects = sorted(SUBJECT_MAP.keys(), key=len, reverse=True)
    for subj in sorted_subjects:
        if subj in title or subj in title_normalized:
            broader = SUBJECT_MAP[subj]
            if broader is not None:
                subject_detail = subj
                subject = subj
                broader_subject = broader
            else:
                subject = subj
                broader_subject = None
            break

    # ── 학교급 + 학년 추출 ──
    grade_level = None
    grade_num = None
    grade_tag = None

    # 패턴: 고2, 고등2, 중1, 중학1, 초등3 등
    grade_patterns = [
        (r'고등?(\d)', "고등"),
        (r'고(\d)', "고등"),
        (r'중학?(\d)', "중학"),
        (r'초등?(\d)', "초등"),
    ]
    for pattern, level in grade_patterns:
        m = re.search(pattern, title)
        if m:
            grade_level = level
            grade_num = m.group(1)
            prefix = {"고등": "고", "중학": "중", "초등": "초"}[level]
            grade_tag = f"{prefix}{grade_num}"
            break

    # "N-1", "N-2" 패턴에서 학년 추출 (예: "수학 2-1" → 2학년)
    if not grade_tag:
        semester_match = re.search(r'(\d)-[12]', title)
        if semester_match:
            num = semester_match.group(1)
            if "중" in title or "중학" in title or "중등" in title:
                grade_level = "중학"
                grade_tag = f"중{num}"
                grade_num = num
            elif "초" in title or "초등" in title:
                grade_level = "초등"
                grade_tag = f"초{num}"
                grade_num = num
            elif "고" in title or "고등" in title:
                grade_level = "고등"
                grade_tag = f"고{num}"
                grade_num = num

    # 학교급만 (학년 번호 없이)
    if not grade_level:
        for keyword in ["고등", "중학", "중등", "초등"]:
            if keyword in title:
                grade_level = GRADE_LEVEL_TAGS.get(keyword, [keyword])[0]
                if grade_level == "중등":
                    grade_level = "중학"
                break

    # 수능 키워드 → 고등으로 처리
    if not grade_level and ("수능" in title or "EBS" in title):
        grade_level = "고등"

    # ── 연도 추출 ──
    year = None
    year_match = re.search(r'(202\d)', title)
    if year_match:
        year = year_match.group(1)

    # ── 저자 클리닝 ──
    clean_author = ""
    if author:
        clean_author = re.sub(r'\s*\(.*?\)', '', author).strip()

    # ── 제목 핵심 단어 추출 ──
    stopwords = {
        'the', 'a', 'an', 'of', 'for', 'and', '전', '권', '개', '세트', '셋',
        '상', '하', '중', '편', '판', '개정', '개정판', '최신판', '신판',
        '사은품', '증정', '포함', '구성', '전2권', '전3권', '전4권', '전5권',
        '전6권', '년', '년도',
    }
    title_clean = re.sub(r'[(\[\])\-+/,~·:\"\'()]', ' ', title)
    title_clean = re.sub(r'\d{4}년?', ' ', title_clean)  # 연도 제거
    words = []
    for w in title_clean.split():
        w = w.strip()
        if len(w) >= 2 and w.lower() not in stopwords and not w.isdigit():
            words.append(w)

    # ── 교재 유형 ──
    material_type = None
    for mt in MATERIAL_TYPES:
        if mt in title:
            material_type = mt
            break

    # ── 자격증명 추출 ──
    cert_name = None
    cert_abbrevs = []
    cert_level = None
    cert_type = None
    for full_name, abbrevs in CERT_ABBREVIATIONS.items():
        if full_name in title or full_name in title_normalized:
            cert_name = full_name
            cert_abbrevs = abbrevs
            break
    for lv in CERT_LEVELS:
        if lv in title:
            cert_level = lv
            break
    for ct in CERT_TYPES:
        if ct in title:
            cert_type = ct
            break

    # ── IT 키워드 추출 ──
    matched_it_keywords = []
    for keyword, related in IT_KEYWORDS.items():
        if keyword in title or keyword in title_normalized:
            matched_it_keywords.append((keyword, related))

    return {
        "series": series,
        "subject": subject,
        "broader_subject": broader_subject,
        "subject_detail": subject_detail,
        "grade_level": grade_level,
        "grade_num": grade_num,
        "grade_tag": grade_tag,
        "year": year,
        "publisher": publisher,
        "author": clean_author,
        "title_words": words,
        "material_type": material_type,
        "cert_name": cert_name,
        "cert_abbrevs": cert_abbrevs,
        "cert_level": cert_level,
        "cert_type": cert_type,
        "it_keywords": matched_it_keywords,
    }


def generate_search_tags(product_name: str,
                         publisher: str = "",
                         author: str = "",
                         category: str = "") -> List[str]:
    """
    완자 화학 1등 상품 패턴 기반 검색 태그 생성 (최대 20개)

    핵심 패턴:
    1. [시리즈] [과목] / [시리즈][과목]  (띄어쓰기 + 붙여쓰기)
    2. [시리즈] [학교급] [과목] / [시리즈][학교급][과목]
    3. [학년] [과목] / [학년][과목]
    4. [과목] [시리즈] / [학년] [과목] [시리즈]  (역순)
    5. [시리즈] [과목] [연도]  (연도 포함)
    6. [학년] [상위과목] [유형]  (상위 카테고리)
    """
    c = extract_components(product_name, publisher, author, category)

    series = c["series"]
    subject = c["subject"]
    broader = c["broader_subject"]
    grade_level = c["grade_level"]
    grade_tag = c["grade_tag"]
    year = c["year"]
    pub = c["publisher"]
    auth = c["author"]
    words = c["title_words"]
    material_type = c["material_type"]
    subject_detail = c["subject_detail"]

    tags = []

    def add(tag: str):
        """태그 추가 (중복 방지, ㆍ 등 API 거부 문자 제거)"""
        t = tag.replace('ㆍ', '')  # U+318D 한글 반시옷 (API 검색어 거부)
        t = _TAG_STRIP_RE.sub('', t).strip()[:20]
        if t and t not in tags:
            tags.append(t)

    # ── (1) 시리즈 + 과목 조합 (최고 우선순위) ──
    if series and subject:
        add(f"{series} {subject}")       # 완자 화학
        add(f"{series}{subject}")         # 완자화학

    # ── (2) 시리즈 + 학교급 + 과목 ──
    if series and grade_level and subject:
        add(f"{series} {grade_level} {subject}")    # 완자 고등 화학
        add(f"{series}{grade_level}{subject}")       # 완자고등화학

    # ── (3) 시리즈 + 학년 + 과목 ──
    if series and grade_tag and subject:
        add(f"{series} {grade_tag} {subject}")       # 완자 고2 화학

    # ── (4) 학년 + 과목 ──
    if grade_tag and subject:
        add(f"{grade_tag} {subject}")     # 고2 화학
        add(f"{grade_tag}{subject}")       # 고2화학

    # ── (5) 역순: 과목 + 시리즈 ──
    if subject and series:
        add(f"{subject} {series}")         # 화학 완자

    # ── (6) 역순: 학년 + 과목 + 시리즈 ──
    if grade_tag and subject and series:
        add(f"{grade_tag} {subject} {series}")   # 고2 화학 완자

    # ── (7) 학년 + 상위과목 + 시리즈/유형 ──
    if grade_tag and broader and broader != subject:
        add(f"{grade_tag} {broader}")                  # 고2 과학
        if series:
            add(f"{grade_tag} {broader} {series}")     # 고2 과학 완자
        if material_type:
            add(f"{grade_tag} {broader} {material_type}")  # 고2 과학 문제집

    # ── (8) 연도 조합 ──
    if year:
        if series and subject:
            add(f"{series} {subject} {year}")          # 완자 화학 2026
        if series and grade_level and subject:
            add(f"{series} {grade_level} {subject} {year}")  # 완자 고등 화학 2026

    # ── (9) 개별 구성요소 ──
    if series:
        add(series)
    if subject:
        add(subject)
    if broader and broader != subject:
        add(broader)

    # ── (10) 출판사 (시리즈와 다를 때만) ──
    if pub and pub != series:
        add(pub)
        if subject:
            add(f"{pub} {subject}")        # 비상 수학

    # ── (11) 저자 ──
    if auth and auth != pub and auth != series:
        add(auth)

    # ── (12) 자격증 약어 + 등급/유형 조합 ──
    cert_name = c.get("cert_name")
    cert_abbrevs = c.get("cert_abbrevs", [])
    cert_level = c.get("cert_level")
    cert_type = c.get("cert_type")

    if cert_name:
        for abbr in cert_abbrevs:
            add(abbr)                                      # 컴활
            if cert_level:
                add(f"{abbr} {cert_level}")                # 컴활 1급
            if cert_type:
                add(f"{abbr} {cert_type}")                 # 컴활 필기
            if cert_level and cert_type:
                add(f"{abbr} {cert_level} {cert_type}")    # 컴활 1급 필기
        # 원래 이름 + 등급 조합
        if cert_level:
            add(f"{cert_name} {cert_level}")               # 컴퓨터활용능력 1급
        if cert_level and cert_type:
            add(f"{cert_name} {cert_level} {cert_type}")   # 20자 초과 시 자동 잘림

    # ── (13) IT/코딩 키워드 보강 ──
    it_kws = c.get("it_keywords", [])
    for keyword, related in it_kws:
        for rel in related:
            if len(tags) >= 18:
                break
            add(rel)

    # ── (14) 시리즈 인기 검색어 보강 ──
    if series and series in SERIES_BOOST_TAGS:
        for boost_tag in SERIES_BOOST_TAGS[series]:
            if len(tags) >= 18:
                break
            add(boost_tag)

    # ── (15) 제목 핵심 단어들 (아직 빈 슬롯이면) ──
    for w in words:
        if len(tags) >= 18:
            break
        if w not in tags and w != series and w != subject and w != pub:
            add(w)

    # ── (16) 학교급 관련 태그 ──
    if grade_level and grade_level in GRADE_LEVEL_TAGS:
        for gt in GRADE_LEVEL_TAGS[grade_level]:
            if len(tags) >= 20:
                break
            add(gt)

    # ── (17) 연도 태그 ──
    if year and len(tags) < 20:
        add(f"{year}년")

    # ── (18) 교재 유형 ──
    if material_type and len(tags) < 20:
        add(material_type)

    return tags[:20]


def update_product_search_tags(
    client: CoupangWingClient,
    seller_product_id: str,
    new_tags: List[str],
    raw_json: str,
) -> Tuple[bool, str]:
    """
    기존 상품의 searchTags만 업데이트 (가격/배송비 변경 없음)

    쿠팡 WING API 상품 수정 방식:
    - PUT /seller-products (base path, ID는 body에)
    - requested=True로 즉시 승인 요청 (검색태그 변경은 즉시 승인됨)
    - GET 응답에서 필요한 필드만 추출하여 깔끔한 payload 구성
    """
    try:
        data = json.loads(raw_json)
        product = data.get("data", data)
        items = product.get("items", [])
        if not items:
            return False, "items가 비어있음"

        # 현재 태그와 동일하면 스킵
        current_tags = items[0].get("searchTags", [])
        if set(current_tags) == set(new_tags) and len(current_tags) == len(new_tags):
            return True, "태그 동일 (스킵)"

        # 깔끔한 PUT payload 구성 (생성 API 형식 + sellerProductId)
        pid = int(seller_product_id)
        payload = {
            "sellerProductId": pid,
            "displayCategoryCode": product["displayCategoryCode"],
            "sellerProductName": product["sellerProductName"],
            "vendorId": product["vendorId"],
            "saleStartedAt": product.get("saleStartedAt", ""),
            "saleEndedAt": product.get("saleEndedAt", "2099-12-31T00:00:00"),
            "displayProductName": product.get("displayProductName", ""),
            "brand": product.get("brand", ""),
            "generalProductName": product.get("generalProductName", ""),
            "productGroup": product.get("productGroup", ""),
            "deliveryMethod": product["deliveryMethod"],
            "deliveryCompanyCode": product.get("deliveryCompanyCode", "HANJIN"),
            "deliveryChargeType": product["deliveryChargeType"],
            "deliveryCharge": product["deliveryCharge"],
            "freeShipOverAmount": product.get("freeShipOverAmount", 0),
            "deliveryChargeOnReturn": product.get("deliveryChargeOnReturn", 0),
            "remoteAreaDeliverable": product.get("remoteAreaDeliverable", "N"),
            "unionDeliveryType": product.get("unionDeliveryType", "UNION_DELIVERY"),
            "returnCenterCode": product["returnCenterCode"],
            "returnChargeName": product.get("returnChargeName", ""),
            "companyContactNumber": product.get("companyContactNumber", ""),
            "returnZipCode": product.get("returnZipCode", ""),
            "returnAddress": product.get("returnAddress", ""),
            "returnAddressDetail": product.get("returnAddressDetail", ""),
            "returnCharge": product.get("returnCharge", 0),
            "outboundShippingPlaceCode": product["outboundShippingPlaceCode"],
            "vendorUserId": product.get("vendorUserId", ""),
            "requested": True,  # 즉시 승인 요청
            "manufacture": product.get("manufacture", ""),
            "items": [],
        }

        # items 구성 (sellerProductItemId 포함 — 기존 아이템 식별 필수)
        for item in items:
            item_payload = {
                "sellerProductItemId": item["sellerProductItemId"],
                "itemName": item["itemName"],
                "originalPrice": item["originalPrice"],
                "salePrice": item["salePrice"],
                "maximumBuyCount": item.get("maximumBuyCount", 1000),
                "maximumBuyForPerson": item.get("maximumBuyForPerson", 0),
                "maximumBuyForPersonPeriod": item.get("maximumBuyForPersonPeriod", 1),
                "outboundShippingTimeDay": item.get("outboundShippingTimeDay", 1),
                "unitCount": item.get("unitCount", 1),
                "adultOnly": item.get("adultOnly", "EVERYONE"),
                "taxType": item.get("taxType", "FREE"),
                "parallelImported": item.get("parallelImported", "NOT_PARALLEL_IMPORTED"),
                "overseasPurchased": item.get("overseasPurchased", "NOT_OVERSEAS_PURCHASED"),
                "pccNeeded": item.get("pccNeeded", False),
                "offerCondition": item.get("offerCondition", "NEW"),
                "barcode": item.get("barcode", ""),
                "emptyBarcode": item.get("emptyBarcode", True),
                "emptyBarcodeReason": item.get("emptyBarcodeReason", ""),
                "modelNo": item.get("modelNo", ""),
                "externalVendorSku": item.get("externalVendorSku", ""),
                "searchTags": new_tags,
                "images": item.get("images", []),
                "notices": item.get("notices", []),
                "attributes": _dedupe_attributes(item.get("attributes", [])),
                "contents": item.get("contents", []),
                "certifications": item.get("certifications", []),
            }
            payload["items"].append(item_payload)

        # PUT to base path (ID는 body의 sellerProductId)
        base_path = "/v2/providers/seller_api/apis/api/v1/marketplace/seller-products"
        result = client._request("PUT", base_path, data=payload)
        code = result.get("code", "")
        if code == "SUCCESS":
            return True, "성공"
        return False, f"응답: {str(result)[:100]}"

    except CoupangWingError as e:
        return False, f"API 오류: {e}"
    except Exception as e:
        return False, f"예외: {e}"


def main():
    parser = argparse.ArgumentParser(description="검색 태그 일괄 업데이트")
    parser.add_argument("--account", type=str, help="특정 계정만 (예: 007-book)")
    parser.add_argument("--limit", type=int, default=0, help="처리할 최대 상품 수 (0=전체)")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 태그만 미리보기")
    parser.add_argument("--delay", type=float, default=0.3, help="API 호출 간 대기 (초)")
    parser.add_argument("--skip-existing", action="store_true", help="이미 태그가 있는 상품 스킵")
    args = parser.parse_args()

    db = SessionLocal()

    try:
        # 대상 계정 조회
        account_query = db.query(Account).filter(Account.wing_api_enabled == True)
        if args.account:
            account_query = account_query.filter(Account.account_name == args.account)
        accounts = account_query.all()

        if not accounts:
            logger.error("대상 계정 없음")
            return

        logger.info(f"대상 계정: {[a.account_name for a in accounts]}")

        total_updated = 0
        total_skipped = 0
        total_failed = 0
        total_same = 0

        for account in accounts:
            logger.info(f"\n{'='*60}")
            logger.info(f"계정: {account.account_name} (vendor_id={account.vendor_id})")
            logger.info(f"{'='*60}")

            # 해당 계정의 listing 조회
            query = db.query(Listing).filter(
                Listing.account_id == account.id,
                Listing.coupang_product_id != None,
                Listing.raw_json != None,
            )

            listings = query.all()
            logger.info(f"  총 {len(listings)}개 listing")

            # WING API 클라이언트
            client = None
            if not args.dry_run:
                client = CoupangWingClient(
                    vendor_id=account.vendor_id,
                    access_key=account.wing_access_key,
                    secret_key=account.wing_secret_key,
                )

            processed = 0
            for listing in listings:
                if args.limit and processed >= args.limit:
                    break

                # 기존 태그 확인
                raw_data = json.loads(listing.raw_json)
                prod_data = raw_data.get("data", raw_data)
                items = prod_data.get("items", [])
                if not items:
                    continue

                current_tags = items[0].get("searchTags", [])
                if args.skip_existing and current_tags:
                    total_skipped += 1
                    continue

                # Book 데이터 조회
                book = None
                if listing.isbn:
                    book = db.query(Book).filter(Book.isbn == listing.isbn).first()

                # 새 태그 생성
                product_name = listing.product_name or prod_data.get("sellerProductName", "")
                pub_name = ""
                auth_name = ""
                cat_name = ""
                if book:
                    pub_name = book.publisher.name if book.publisher else ""
                    auth_name = ""  # author 컬럼 삭제됨
                    cat_name = ""  # category 컬럼 삭제됨
                elif listing.brand:
                    pub_name = listing.brand

                new_tags = generate_search_tags(product_name, pub_name, auth_name, cat_name)

                if not new_tags:
                    total_skipped += 1
                    continue

                # 동일한 태그면 스킵
                if set(current_tags) == set(new_tags) and len(current_tags) == len(new_tags):
                    total_same += 1
                    continue

                processed += 1

                if args.dry_run:
                    logger.info(f"\n  [{processed}] {product_name[:50]}")
                    logger.info(f"    현재: {current_tags}")
                    logger.info(f"    신규: {new_tags}")
                    total_updated += 1
                else:
                    success, msg = update_product_search_tags(
                        client,
                        listing.coupang_product_id,
                        new_tags,
                        listing.raw_json,
                    )

                    if success:
                        if "스킵" in msg:
                            total_same += 1
                        else:
                            total_updated += 1
                            logger.info(f"  [{processed}] OK: {product_name[:40]} → {len(new_tags)}개 태그")
                    else:
                        total_failed += 1
                        logger.warning(f"  [{processed}] FAIL: {product_name[:40]} → {msg}")

                    time.sleep(args.delay)

        # 결과 요약
        logger.info(f"\n{'='*60}")
        logger.info(f"완료!")
        logger.info(f"  업데이트: {total_updated}")
        logger.info(f"  동일(스킵): {total_same}")
        logger.info(f"  스킵: {total_skipped}")
        logger.info(f"  실패: {total_failed}")
        logger.info(f"{'='*60}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
