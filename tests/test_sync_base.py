"""
wing_sync_base.py 테스트
========================
SQL 인젝션 방지, 공통 유틸리티 테스트
"""
import pytest
import sys
import tempfile
from pathlib import Path

# 프로젝트 루트 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text

from app.services.wing_sync_base import WingSyncBase, get_accounts
from app.services.transaction_manager import atomic_operation, BatchProcessor
from app.services.db_migration import SQLiteMigrator


class TestWingSyncBase:
    """WingSyncBase 클래스 테스트"""

    def setup_method(self):
        """테스트용 임시 DB 생성"""
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        # 테스트용 accounts 테이블 생성
        with self.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE accounts (
                    id INTEGER PRIMARY KEY,
                    account_name VARCHAR(50),
                    vendor_id VARCHAR(20),
                    wing_access_key VARCHAR(100),
                    wing_secret_key VARCHAR(100),
                    is_active BOOLEAN DEFAULT 1,
                    wing_api_enabled BOOLEAN DEFAULT 1
                )
            """))
            # 테스트 데이터 삽입
            conn.execute(text("""
                INSERT INTO accounts (account_name, vendor_id, wing_access_key, wing_secret_key, is_active, wing_api_enabled)
                VALUES ('test-account', 'V123', 'access123', 'secret456', 1, 1)
            """))
            conn.execute(text("""
                INSERT INTO accounts (account_name, vendor_id, wing_access_key, wing_secret_key, is_active, wing_api_enabled)
                VALUES ('inactive-account', 'V456', 'access789', 'secret012', 0, 1)
            """))
            conn.commit()

    def teardown_method(self):
        """임시 DB 정리"""
        self.engine.dispose()  # SQLite 연결 해제
        self.temp_db.close()
        try:
            Path(self.db_path).unlink(missing_ok=True)
        except PermissionError:
            pass  # Windows 파일 잠금 무시

    def test_get_accounts_all(self):
        """전체 계정 조회"""
        accounts = get_accounts(self.engine)
        assert len(accounts) == 1  # 활성 계정만
        assert accounts[0]["account_name"] == "test-account"

    def test_get_accounts_by_name(self):
        """특정 계정 조회"""
        accounts = get_accounts(self.engine, "test-account")
        assert len(accounts) == 1
        assert accounts[0]["vendor_id"] == "V123"

    def test_get_accounts_not_found(self):
        """존재하지 않는 계정"""
        accounts = get_accounts(self.engine, "nonexistent")
        assert len(accounts) == 0

    def test_sql_injection_prevention(self):
        """SQL 인젝션 방지 테스트"""
        # 악의적인 입력으로 SQL 인젝션 시도
        malicious_input = "'; DROP TABLE accounts; --"
        accounts = get_accounts(self.engine, malicious_input)

        # 테이블이 삭제되지 않았는지 확인
        assert len(accounts) == 0  # 단순히 없는 계정

        # 테이블이 여전히 존재하는지 확인
        all_accounts = get_accounts(self.engine)
        assert len(all_accounts) == 1  # 여전히 1개 (활성 계정)


class TestAtomicOperation:
    """atomic_operation 테스트"""

    def setup_method(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE test_items (id INTEGER PRIMARY KEY, name TEXT)"))
            conn.commit()

    def teardown_method(self):
        self.engine.dispose()
        self.temp_db.close()
        try:
            Path(self.db_path).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_commit_on_success(self):
        """성공 시 커밋"""
        with atomic_operation(self.engine) as conn:
            conn.execute(text("INSERT INTO test_items (name) VALUES ('item1')"))

        # 커밋 확인
        with self.engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM test_items")).scalar()
            assert count == 1

    def test_rollback_on_error(self):
        """오류 시 롤백"""
        try:
            with atomic_operation(self.engine) as conn:
                conn.execute(text("INSERT INTO test_items (name) VALUES ('item1')"))
                raise ValueError("테스트 오류")
        except ValueError:
            pass

        # 롤백 확인
        with self.engine.connect() as conn:
            count = conn.execute(text("SELECT COUNT(*) FROM test_items")).scalar()
            assert count == 0


class TestBatchProcessor:
    """BatchProcessor 테스트"""

    def setup_method(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)"))
            conn.commit()

    def teardown_method(self):
        self.engine.dispose()
        self.temp_db.close()
        try:
            Path(self.db_path).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_process_batch_success(self):
        """배치 처리 성공"""
        processor = BatchProcessor(self.engine, batch_size=2)

        def process_item(conn, item):
            conn.execute(text("INSERT INTO items (value) VALUES (:val)"), {"val": item})
            return {"item": item, "status": "ok"}

        items = ["a", "b", "c"]
        result = processor.process_batch(items, process_item)

        assert result["success_count"] == 3
        assert result["fail_count"] == 0
        assert len(result["success"]) == 3

    def test_process_batch_with_errors(self):
        """일부 실패하는 배치 처리"""
        processor = BatchProcessor(self.engine, batch_size=2, continue_on_error=True)

        call_count = 0

        def process_item(conn, item):
            nonlocal call_count
            call_count += 1
            if item == "bad":
                raise ValueError("의도적 오류")
            conn.execute(text("INSERT INTO items (value) VALUES (:val)"), {"val": item})
            return {"item": item}

        items = ["a", "bad", "c"]
        result = processor.process_batch(items, process_item)

        assert result["success_count"] == 2
        assert result["fail_count"] == 1
        assert call_count == 3  # 모두 시도됨


class TestSQLiteMigrator:
    """SQLiteMigrator 테스트"""

    def setup_method(self):
        self.temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.db_path = self.temp_db.name
        self.engine = create_engine(f"sqlite:///{self.db_path}")

        with self.engine.connect() as conn:
            conn.execute(text("CREATE TABLE test_table (id INTEGER PRIMARY KEY)"))
            conn.commit()

    def teardown_method(self):
        self.engine.dispose()
        self.temp_db.close()
        try:
            Path(self.db_path).unlink(missing_ok=True)
        except PermissionError:
            pass

    def test_add_columns_if_missing(self):
        """누락된 컬럼 추가"""
        migrator = SQLiteMigrator(self.engine)

        added = migrator.add_columns_if_missing("test_table", {
            "name": "TEXT",
            "value": "INTEGER DEFAULT 0",
        })

        assert len(added) == 2
        assert "name" in added
        assert "value" in added

    def test_add_columns_already_exist(self):
        """이미 존재하는 컬럼은 무시"""
        migrator = SQLiteMigrator(self.engine)

        # 첫 번째 추가
        added1 = migrator.add_columns_if_missing("test_table", {"name": "TEXT"})
        assert len(added1) == 1

        # 두 번째 추가 시도 (무시되어야 함)
        migrator._inspector = None  # 캐시 리셋
        added2 = migrator.add_columns_if_missing("test_table", {"name": "TEXT"})
        assert len(added2) == 0

    def test_table_exists(self):
        """테이블 존재 확인"""
        migrator = SQLiteMigrator(self.engine)

        assert migrator.table_exists("test_table") is True
        assert migrator.table_exists("nonexistent_table") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
