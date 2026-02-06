"""
validators.py 테스트
====================
BookValidator, ProductValidator 테스트
"""
import pytest
import sys
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.utils.validators import (
    BookValidator,
    ProductValidator,
    ValidationError,
    validate_book_data,
    validate_product_for_upload,
)


class TestBookValidator:
    """BookValidator 테스트"""

    def setup_method(self):
        self.validator = BookValidator()

    # ─── ISBN 검증 테스트 ───

    def test_valid_isbn13(self):
        """유효한 ISBN-13"""
        # 실제 책의 ISBN
        assert self.validator.validate_isbn("9788956746425") is None
        assert self.validator.validate_isbn("978-89-567-4642-5") is None  # 하이픈 포함

    def test_valid_isbn10(self):
        """유효한 ISBN-10"""
        assert self.validator.validate_isbn("8956746427") is None

    def test_invalid_isbn_prefix(self):
        """잘못된 ISBN 접두사"""
        error = self.validator.validate_isbn("9998956746425")
        assert error is not None
        assert "978/979" in error.message

    def test_invalid_isbn_length(self):
        """잘못된 ISBN 길이"""
        error = self.validator.validate_isbn("12345")
        assert error is not None
        assert "길이" in error.message

    def test_empty_isbn(self):
        """빈 ISBN"""
        error = self.validator.validate_isbn("")
        assert error is not None
        assert "비어" in error.message

    # ─── 가격 검증 테스트 ───

    def test_valid_price(self):
        """유효한 가격"""
        assert self.validator.validate_price(15000) is None
        assert self.validator.validate_price("15000") is None  # 문자열도 OK

    def test_price_too_low(self):
        """가격이 너무 낮음"""
        error = self.validator.validate_price(500)
        assert error is not None
        assert "너무 낮" in error.message

    def test_price_too_high(self):
        """가격이 너무 높음"""
        error = self.validator.validate_price(1000000)
        assert error is not None
        assert "너무 높" in error.message

    def test_price_not_number(self):
        """가격이 숫자가 아님"""
        error = self.validator.validate_price("abc")
        assert error is not None
        assert "숫자가 아닙니다" in error.message

    def test_price_none(self):
        """가격이 None"""
        error = self.validator.validate_price(None)
        assert error is not None

    # ─── 제목 검증 테스트 ───

    def test_valid_title(self):
        """유효한 제목"""
        assert self.validator.validate_title("수학의 정석") is None

    def test_empty_title(self):
        """빈 제목"""
        error = self.validator.validate_title("")
        assert error is not None
        assert "비어" in error.message

    def test_title_too_long(self):
        """제목이 너무 김"""
        long_title = "가" * 600
        error = self.validator.validate_title(long_title)
        assert error is not None
        assert "너무 깁니다" in error.message

    # ─── 전체 검증 테스트 ───

    def test_validate_complete_book(self):
        """전체 도서 데이터 검증 - 유효"""
        book = {
            "isbn": "9788956746425",
            "title": "수학의 정석",
            "price": 15000,
        }
        errors = self.validator.validate(book)
        assert len(errors) == 0

    def test_validate_book_with_errors(self):
        """전체 도서 데이터 검증 - 오류 있음"""
        book = {
            "isbn": "invalid",
            "title": "",
            "price": 500,
        }
        errors = self.validator.validate(book)
        assert len(errors) >= 2  # ISBN, 가격 오류


class TestProductValidator:
    """ProductValidator 테스트"""

    def setup_method(self):
        self.validator = ProductValidator()

    def test_valid_product(self):
        """유효한 상품 데이터"""
        product = {
            "display_category_code": "76236",
            "product_name": "수학의 정석",
            "vendor_item_id": "123456",
            "sale_price": 15000,
            "isbn": "9788956746425",
        }
        is_valid, errors = self.validator.validate_for_upload(product)
        assert is_valid
        assert len(errors) == 0

    def test_missing_required_fields(self):
        """필수 필드 누락"""
        product = {
            "product_name": "테스트 상품",
        }
        is_valid, errors = self.validator.validate_for_upload(product)
        assert not is_valid
        assert len(errors) >= 2  # category, vendor_item_id, sale_price 중 일부

    def test_invalid_category_code(self):
        """잘못된 카테고리 코드"""
        product = {
            "display_category_code": "abc",
            "product_name": "테스트",
            "vendor_item_id": "123",
            "sale_price": 15000,
        }
        is_valid, errors = self.validator.validate_for_upload(product)
        assert not is_valid
        assert any("카테고리" in e.message for e in errors)

    def test_sanitize_product_name(self):
        """상품명 정제"""
        # 연속 공백 제거
        result = self.validator.sanitize_product_name("수학의   정석")
        assert result == "수학의 정석"

        # 길이 제한
        long_name = "가" * 200
        result = self.validator.sanitize_product_name(long_name, max_length=50)
        assert len(result) <= 50
        assert result.endswith("...")


class TestHelperFunctions:
    """헬퍼 함수 테스트"""

    def test_validate_book_data_valid(self):
        """validate_book_data - 유효"""
        book = {"isbn": "9788956746425", "title": "테스트", "price": 15000}
        is_valid, errors = validate_book_data(book)
        assert is_valid
        assert len(errors) == 0

    def test_validate_book_data_invalid(self):
        """validate_book_data - 무효"""
        book = {"isbn": "invalid", "price": 0}
        is_valid, errors = validate_book_data(book)
        assert not is_valid
        assert len(errors) > 0

    def test_validate_product_for_upload_valid(self):
        """validate_product_for_upload - 유효"""
        product = {
            "display_category_code": "76236",
            "product_name": "테스트",
            "vendor_item_id": "123",
            "sale_price": 15000,
        }
        is_valid, errors = validate_product_for_upload(product)
        assert is_valid

    def test_validate_product_for_upload_invalid(self):
        """validate_product_for_upload - 무효"""
        product = {}
        is_valid, errors = validate_product_for_upload(product)
        assert not is_valid


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
