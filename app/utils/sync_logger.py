"""
동기화 로거 모듈
================
동기화 작업의 성공/실패 기록, JSON 리포트 생성

사용법:
    logger = SyncLogger("revenue_sync")
    logger.log_success(account="007-book", count=100)
    logger.log_failure(account="007-bm", error="API 오류", item_id=123)
    report = logger.end_sync()
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

# 기본 로그 디렉토리
DEFAULT_LOG_DIR = Path(__file__).parent.parent.parent / "logs"


@dataclass
class SyncFailure:
    """동기화 실패 항목"""
    timestamp: str
    account: str
    error: str
    item_id: Optional[str] = None
    item_name: Optional[str] = None
    details: Optional[Dict] = None


@dataclass
class SyncResult:
    """동기화 결과 요약"""
    sync_type: str
    started_at: str
    ended_at: str
    duration_seconds: float
    total_processed: int
    success_count: int
    failure_count: int
    accounts: Dict[str, Dict[str, int]]
    failures: List[Dict]


class SyncLogger:
    """
    동기화 로거

    각 동기화 세션의 성공/실패를 기록하고 JSON 리포트 생성

    Attributes:
        sync_type: 동기화 유형 (revenue, inventory, settlement 등)
        log_dir: 로그 저장 디렉토리
    """

    def __init__(
        self,
        sync_type: str,
        log_dir: Optional[Path] = None,
        max_failures: int = 1000,
    ):
        """
        Args:
            sync_type: 동기화 유형 이름
            log_dir: 로그 저장 디렉토리 (None=기본)
            max_failures: 저장할 최대 실패 항목 수
        """
        self.sync_type = sync_type
        self.log_dir = log_dir or DEFAULT_LOG_DIR
        self.log_dir.mkdir(exist_ok=True)
        self.max_failures = max_failures

        self.started_at = datetime.now()
        self.ended_at: Optional[datetime] = None

        # 계정별 통계
        self._accounts: Dict[str, Dict[str, int]] = {}
        # 실패 항목 리스트
        self._failures: List[SyncFailure] = []
        # 전체 카운터
        self._total_processed = 0
        self._success_count = 0
        self._failure_count = 0

    def log_success(
        self,
        account: str,
        count: int = 1,
        **extra,
    ):
        """
        성공 기록

        Args:
            account: 계정명
            count: 성공 건수
            **extra: 추가 데이터 (통계용)
        """
        if account not in self._accounts:
            self._accounts[account] = {"success": 0, "failure": 0}

        self._accounts[account]["success"] += count
        self._success_count += count
        self._total_processed += count

        for key, value in extra.items():
            if key not in self._accounts[account]:
                self._accounts[account][key] = 0
            self._accounts[account][key] += value

    def log_failure(
        self,
        account: str,
        error: str,
        item_id: Optional[str] = None,
        item_name: Optional[str] = None,
        details: Optional[Dict] = None,
    ):
        """
        실패 기록

        Args:
            account: 계정명
            error: 오류 메시지
            item_id: 실패한 항목 ID
            item_name: 실패한 항목 이름
            details: 추가 상세 정보
        """
        if account not in self._accounts:
            self._accounts[account] = {"success": 0, "failure": 0}

        self._accounts[account]["failure"] += 1
        self._failure_count += 1
        self._total_processed += 1

        if len(self._failures) < self.max_failures:
            failure = SyncFailure(
                timestamp=datetime.now().isoformat(),
                account=account,
                error=str(error)[:500],  # 오류 메시지 길이 제한
                item_id=str(item_id) if item_id else None,
                item_name=str(item_name)[:200] if item_name else None,
                details=details,
            )
            self._failures.append(failure)

    def end_sync(self, save_report: bool = True) -> SyncResult:
        """
        동기화 종료 및 리포트 생성

        Args:
            save_report: JSON 파일로 저장할지 여부

        Returns:
            SyncResult 객체
        """
        self.ended_at = datetime.now()
        duration = (self.ended_at - self.started_at).total_seconds()

        result = SyncResult(
            sync_type=self.sync_type,
            started_at=self.started_at.isoformat(),
            ended_at=self.ended_at.isoformat(),
            duration_seconds=round(duration, 2),
            total_processed=self._total_processed,
            success_count=self._success_count,
            failure_count=self._failure_count,
            accounts=self._accounts,
            failures=[asdict(f) for f in self._failures],
        )

        if save_report:
            self._save_report(result)

        # 요약 로그
        logger.info(
            f"[{self.sync_type}] 동기화 완료: "
            f"처리 {self._total_processed}건, "
            f"성공 {self._success_count}건, "
            f"실패 {self._failure_count}건, "
            f"소요 {duration:.1f}초"
        )

        return result

    def _save_report(self, result: SyncResult):
        """JSON 리포트 파일 저장"""
        date_str = self.started_at.strftime("%Y%m%d_%H%M%S")
        filename = f"{self.sync_type}_{date_str}.json"
        filepath = self.log_dir / filename

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(asdict(result), f, ensure_ascii=False, indent=2)
            logger.info(f"리포트 저장: {filepath}")
        except Exception as e:
            logger.error(f"리포트 저장 실패: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """현재까지의 요약 반환"""
        return {
            "sync_type": self.sync_type,
            "started_at": self.started_at.isoformat(),
            "elapsed_seconds": (datetime.now() - self.started_at).total_seconds(),
            "total_processed": self._total_processed,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "accounts": self._accounts,
        }

    @property
    def has_failures(self) -> bool:
        """실패 항목이 있는지"""
        return self._failure_count > 0

    @property
    def failure_rate(self) -> float:
        """실패율 (0.0 ~ 1.0)"""
        if self._total_processed == 0:
            return 0.0
        return self._failure_count / self._total_processed


def load_sync_report(filepath: Path) -> Optional[SyncResult]:
    """
    저장된 리포트 로드

    Args:
        filepath: 리포트 파일 경로

    Returns:
        SyncResult 객체 또는 None
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SyncResult(**data)
    except Exception as e:
        logger.error(f"리포트 로드 실패: {e}")
        return None


def list_sync_reports(
    log_dir: Path = DEFAULT_LOG_DIR,
    sync_type: Optional[str] = None,
    limit: int = 10,
) -> List[Path]:
    """
    최근 리포트 파일 목록

    Args:
        log_dir: 로그 디렉토리
        sync_type: 특정 타입만 필터링 (None=전체)
        limit: 최대 반환 개수

    Returns:
        파일 경로 리스트 (최신순)
    """
    pattern = f"{sync_type}_*.json" if sync_type else "*.json"
    files = sorted(log_dir.glob(pattern), reverse=True)
    return files[:limit]
