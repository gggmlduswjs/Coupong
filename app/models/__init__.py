"""SQLAlchemy 모델"""
from app.models.account import Account
from app.models.publisher import Publisher
from app.models.book import Book
from app.models.product import Product
from app.models.bundle_sku import BundleSKU
from app.models.listing import Listing
from app.models.sales import Sales
from app.models.analysis_result import AnalysisResult
from app.models.task import Task

# 하위 호환성을 위한 별칭
KyoboProduct = Book  # kyobo_products → books 이름 변경

__all__ = [
    "Account",
    "Publisher",
    "Book",
    "Product",
    "BundleSKU",
    "Listing",
    "Sales",
    "AnalysisResult",
    "Task",
    "KyoboProduct",  # 하위 호환용
]
