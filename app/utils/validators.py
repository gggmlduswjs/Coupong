"""
입력 검증 모듈
==============
도서 정보, 상품 데이터 검증

사용법:
    validator = BookValidator()
    errors = validator.validate(book_data)
    if errors:
        print(f"검증 실패: {errors}")
"""
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ValidationError:
    """검증 오류"""
    field: str
    message: str
    value: Any = None


class BookValidator:
    """
    도서 정보 검증기

    ISBN, 가격, 제목 등 도서 데이터 검증
    """

    # ISBN-13 패턴 (978 또는 979로 시작, 13자리)
    ISBN13_PATTERN = re.compile(r'^97[89]\d{10}$')
    # ISBN-10 패턴 (10자리, 마지막은 숫자 또는 X)
    ISBN10_PATTERN = re.compile(r'^\d{9}[\dX]$')

    # 가격 범위 (한국 도서 기준)
    MIN_PRICE = 1000
    MAX_PRICE = 500000

    # 제목 길이
    MIN_TITLE_LENGTH = 1
    MAX_TITLE_LENGTH = 500

    def validate_isbn(self, isbn: str) -> Optional[ValidationError]:
        """
        ISBN 검증

        Args:
            isbn: ISBN 문자열

        Returns:
            ValidationError 또는 None (유효한 경우)
        """
        if not isbn:
            return ValidationError("isbn", "ISBN이 비어 있습니다")

        # 공백/하이픈 제거
        clean_isbn = re.sub(r'[\s-]', '', str(isbn))

        if len(clean_isbn) == 13:
            if not self.ISBN13_PATTERN.match(clean_isbn):
                return ValidationError(
                    "isbn",
                    "ISBN-13 형식이 아닙니다 (978/979로 시작하는 13자리)",
                    isbn
                )
            # 체크섬 검증
            if not self._verify_isbn13_checksum(clean_isbn):
                return ValidationError("isbn", "ISBN-13 체크섬 오류", isbn)

        elif len(clean_isbn) == 10:
            if not self.ISBN10_PATTERN.match(clean_isbn):
                return ValidationError(
                    "isbn",
                    "ISBN-10 형식이 아닙니다 (10자리)",
                    isbn
                )
        else:
            return ValidationError(
                "isbn",
                f"ISBN 길이 오류 ({len(clean_isbn)}자리, 10 또는 13자리 필요)",
                isbn
            )

        return None

    def _verify_isbn13_checksum(self, isbn: str) -> bool:
        """ISBN-13 체크섬 검증"""
        try:
            total = sum(
                int(digit) * (1 if i % 2 == 0 else 3)
                for i, digit in enumerate(isbn)
            )
            return total % 10 == 0
        except ValueError:
            return False

    def validate_price(
        self,
        price: Any,
        field_name: str = "price",
    ) -> Optional[ValidationError]:
        """
        가격 검증

        Args:
            price: 가격 값
            field_name: 필드명 (오류 메시지용)

        Returns:
            ValidationError 또는 None
        """
        if price is None:
            return ValidationError(field_name, "가격이 없습니다")

        try:
            price_int = int(price)
        except (ValueError, TypeError):
            return ValidationError(
                field_name,
                f"가격이 숫자가 아닙니다: {price}",
                price
            )

        if price_int < self.MIN_PRICE:
            return ValidationError(
                field_name,
                f"가격이 너무 낮습니다 (최소 {self.MIN_PRICE:,}원)",
                price_int
            )

        if price_int > self.MAX_PRICE:
            return ValidationError(
                field_name,
                f"가격이 너무 높습니다 (최대 {self.MAX_PRICE:,}원)",
                price_int
            )

        return None

    def validate_title(self, title: str) -> Optional[ValidationError]:
        """
        제목 검증

        Args:
            title: 도서 제목

        Returns:
            ValidationError 또는 None
        """
        if not title:
            return ValidationError("title", "제목이 비어 있습니다")

        title = str(title).strip()

        if len(title) < self.MIN_TITLE_LENGTH:
            return ValidationError("title", "제목이 너무 짧습니다", title)

        if len(title) > self.MAX_TITLE_LENGTH:
            return ValidationError(
                "title",
                f"제목이 너무 깁니다 (최대 {self.MAX_TITLE_LENGTH}자)",
                title[:100] + "..."
            )

        return None

    def validate(self, book_data: Dict) -> List[ValidationError]:
        """
        도서 데이터 전체 검증

        Args:
            book_data: 도서 데이터 딕셔너리

        Returns:
            ValidationError 리스트 (빈 리스트면 유효)
        """
        errors = []

        # ISBN 검증
        isbn = book_data.get("isbn") or book_data.get("isbn13")
        if isbn:
            err = self.validate_isbn(isbn)
            if err:
                errors.append(err)

        # 가격 검증
        for field in ["price", "sale_price", "regular_price"]:
            if field in book_data and book_data[field]:
                err = self.validate_price(book_data[field], field)
                if err:
                    errors.append(err)

        # 제목 검증
        title = book_data.get("title") or book_data.get("name")
        if title:
            err = self.validate_title(title)
            if err:
                errors.append(err)

        return errors


class ProductValidator:
    """
    상품 데이터 검증기

    쿠팡 업로드 전 필수 필드 검증
    """

    REQUIRED_FIELDS = [
        "display_category_code",
        "product_name",
        "vendor_item_id",
        "sale_price",
    ]

    OPTIONAL_BUT_RECOMMENDED = [
        "isbn",
        "brand",
        "delivery_charge_type",
    ]

    def validate_for_upload(self, product_data: Dict) -> Tuple[bool, List[ValidationError]]:
        """
        업로드 전 전체 검증

        Args:
            product_data: 상품 데이터 딕셔너리

        Returns:
            (유효 여부, 에러 리스트) 튜플
        """
        errors = []
        warnings = []

        # 필수 필드 확인
        for field in self.REQUIRED_FIELDS:
            if not product_data.get(field):
                errors.append(ValidationError(
                    field,
                    f"필수 필드가 비어 있습니다: {field}"
                ))

        # 권장 필드 확인 (경고만)
        for field in self.OPTIONAL_BUT_RECOMMENDED:
            if not product_data.get(field):
                warnings.append(ValidationError(
                    field,
                    f"권장 필드가 비어 있습니다: {field}",
                ))

        # 가격 검증
        book_validator = BookValidator()
        sale_price = product_data.get("sale_price")
        if sale_price:
            err = book_validator.validate_price(sale_price, "sale_price")
            if err:
                errors.append(err)

        # 상품명 검증
        product_name = product_data.get("product_name")
        if product_name:
            err = book_validator.validate_title(product_name)
            if err:
                errors.append(err)

        # 카테고리 코드 형식 검증
        category_code = product_data.get("display_category_code")
        if category_code:
            if not str(category_code).isdigit():
                errors.append(ValidationError(
                    "display_category_code",
                    "카테고리 코드는 숫자여야 합니다",
                    category_code
                ))

        if warnings:
            for w in warnings:
                logger.warning(f"검증 경고: {w.field} - {w.message}")

        is_valid = len(errors) == 0
        return is_valid, errors

    def sanitize_product_name(self, name: str, max_length: int = 100) -> str:
        """
        상품명 정제

        Args:
            name: 원본 상품명
            max_length: 최대 길이

        Returns:
            정제된 상품명
        """
        if not name:
            return ""

        # 특수문자 정리
        name = str(name).strip()
        # 연속 공백 제거
        name = re.sub(r'\s+', ' ', name)
        # 길이 제한
        if len(name) > max_length:
            name = name[:max_length - 3] + "..."

        return name


def validate_book_data(data: Dict) -> Tuple[bool, List[str]]:
    """
    간단한 도서 검증 함수

    Args:
        data: 도서 데이터

    Returns:
        (유효 여부, 에러 메시지 리스트)
    """
    validator = BookValidator()
    errors = validator.validate(data)

    if errors:
        return False, [f"{e.field}: {e.message}" for e in errors]
    return True, []


def validate_product_for_upload(data: Dict) -> Tuple[bool, List[str]]:
    """
    간단한 상품 업로드 검증 함수

    Args:
        data: 상품 데이터

    Returns:
        (유효 여부, 에러 메시지 리스트)
    """
    validator = ProductValidator()
    is_valid, errors = validator.validate_for_upload(data)

    if errors:
        return False, [f"{e.field}: {e.message}" for e in errors]
    return True, []
