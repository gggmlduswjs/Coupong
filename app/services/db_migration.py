"""
SQLite 마이그레이션 유틸리티
============================
컬럼 추가, 테이블 생성 등 스키마 변경

사용법:
    migrator = SQLiteMigrator(engine)
    migrator.add_columns_if_missing("accounts", {
        "vendor_id": "VARCHAR(20)",
        "wing_access_key": "VARCHAR(100)",
    })
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy import text, inspect
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class SQLiteMigrator:
    """SQLite 스키마 마이그레이션 헬퍼"""

    def __init__(self, engine: Engine):
        self.engine = engine
        self._inspector = None

    @property
    def inspector(self):
        """지연 로딩 인스펙터"""
        if self._inspector is None:
            self._inspector = inspect(self.engine)
        return self._inspector

    def get_existing_columns(self, table_name: str) -> set:
        """
        테이블의 기존 컬럼 이름 조회

        Args:
            table_name: 테이블명

        Returns:
            컬럼명 집합

        Raises:
            ValueError: 테이블이 존재하지 않는 경우
        """
        try:
            columns = self.inspector.get_columns(table_name)
            return {col["name"] for col in columns}
        except Exception as e:
            logger.warning(f"테이블 '{table_name}' 조회 실패: {e}")
            raise ValueError(f"테이블 '{table_name}'이 존재하지 않습니다") from e

    def table_exists(self, table_name: str) -> bool:
        """테이블 존재 여부 확인"""
        try:
            self.inspector.get_columns(table_name)
            return True
        except Exception:
            return False

    def add_columns_if_missing(
        self,
        table_name: str,
        columns: Dict[str, str],
        ignore_missing_table: bool = True,
    ) -> List[str]:
        """
        누락된 컬럼만 추가

        Args:
            table_name: 테이블명
            columns: {컬럼명: 타입정의} 딕셔너리
            ignore_missing_table: 테이블이 없으면 무시 (True) / 예외 (False)

        Returns:
            추가된 컬럼명 리스트

        Example:
            added = migrator.add_columns_if_missing("accounts", {
                "vendor_id": "VARCHAR(20)",
                "wing_api_enabled": "BOOLEAN DEFAULT 0",
            })
        """
        try:
            existing = self.get_existing_columns(table_name)
        except ValueError:
            if ignore_missing_table:
                logger.info(f"테이블 '{table_name}' 없음 - 마이그레이션 건너뜀")
                return []
            raise

        added = []
        with self.engine.connect() as conn:
            for col_name, col_type in columns.items():
                if col_name not in existing:
                    sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"
                    conn.execute(text(sql))
                    added.append(col_name)
                    logger.info(f"  컬럼 추가: {table_name}.{col_name}")
            conn.commit()

        return added

    def create_table_if_not_exists(self, create_sql: str) -> bool:
        """
        테이블 생성 (없는 경우에만)

        Args:
            create_sql: CREATE TABLE IF NOT EXISTS ... SQL

        Returns:
            True: 새로 생성됨, False: 이미 존재
        """
        with self.engine.connect() as conn:
            conn.execute(text(create_sql))
            conn.commit()
        return True

    def create_index_if_not_exists(self, index_sql: str) -> bool:
        """
        인덱스 생성 (없는 경우에만)

        Args:
            index_sql: CREATE INDEX IF NOT EXISTS ... SQL

        Returns:
            True: 성공
        """
        with self.engine.connect() as conn:
            conn.execute(text(index_sql))
            conn.commit()
        return True

    def ensure_schema(
        self,
        table_name: str,
        create_sql: str,
        columns: Optional[Dict[str, str]] = None,
        indexes: Optional[List[str]] = None,
    ) -> Dict[str, any]:
        """
        스키마 전체 확인/생성 (테이블 + 컬럼 + 인덱스)

        Args:
            table_name: 테이블명
            create_sql: CREATE TABLE SQL
            columns: 추가할 컬럼들 (마이그레이션용)
            indexes: 생성할 인덱스 SQL 리스트

        Returns:
            {"table_created": bool, "columns_added": list, "indexes_created": int}
        """
        result = {
            "table_created": False,
            "columns_added": [],
            "indexes_created": 0,
        }

        # 1) 테이블 생성
        if not self.table_exists(table_name):
            self.create_table_if_not_exists(create_sql)
            result["table_created"] = True
            logger.info(f"테이블 생성: {table_name}")

        # 2) 컬럼 추가
        if columns:
            result["columns_added"] = self.add_columns_if_missing(
                table_name, columns, ignore_missing_table=False
            )

        # 3) 인덱스 생성
        if indexes:
            for idx_sql in indexes:
                self.create_index_if_not_exists(idx_sql)
                result["indexes_created"] += 1

        return result
