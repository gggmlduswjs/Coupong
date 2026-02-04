"""업로드 작업 큐 관리"""
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class UploadJob:
    """업로드 작업 정의"""
    job_id: str
    account_ids: List[str]  # 대상 계정 목록
    products: List[Dict]    # 업로드할 상품 목록
    created_at: str
    status: str = 'pending'  # pending, running, completed, failed
    priority: int = 1
    dry_run: bool = True
    execution_mode: str = 'sequential'  # sequential or parallel
    max_workers: int = 2  # 병렬 실행 시 최대 워커 수
    result: Optional[Dict] = None
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> 'UploadJob':
        """딕셔너리에서 생성"""
        return cls(**data)


class JobQueue:
    """작업 큐 관리"""

    def __init__(self, queue_file: str = "data/queue/jobs.json"):
        self.queue_file = Path(queue_file)
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        self.jobs = self._load_jobs()

    def _load_jobs(self) -> List[UploadJob]:
        """작업 목록 로드"""
        if self.queue_file.exists():
            try:
                with open(self.queue_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return [UploadJob.from_dict(job) for job in data]
            except Exception as e:
                logger.error(f"작업 큐 로드 실패: {e}")
        return []

    def _save_jobs(self):
        """작업 목록 저장"""
        try:
            data = [job.to_dict() for job in self.jobs]
            with open(self.queue_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"작업 큐 저장 실패: {e}")

    def add_job(
        self,
        account_ids: List[str],
        products: List[Dict],
        priority: int = 1,
        dry_run: bool = True,
        execution_mode: str = 'sequential',
        max_workers: int = 2
    ) -> str:
        """작업 추가"""
        job_id = f"job_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        job = UploadJob(
            job_id=job_id,
            account_ids=account_ids,
            products=products,
            created_at=datetime.now().isoformat(),
            priority=priority,
            dry_run=dry_run,
            execution_mode=execution_mode,
            max_workers=max_workers
        )
        self.jobs.append(job)
        self._save_jobs()
        logger.info(f"작업 추가: {job_id} ({len(products)}개 상품, {len(account_ids)}개 계정)")
        return job_id

    def get_pending_jobs(self) -> List[UploadJob]:
        """대기 중인 작업 목록"""
        return [job for job in self.jobs if job.status == 'pending']

    def get_job(self, job_id: str) -> Optional[UploadJob]:
        """작업 조회"""
        for job in self.jobs:
            if job.job_id == job_id:
                return job
        return None

    def update_job_status(
        self,
        job_id: str,
        status: str,
        result: Optional[Dict] = None,
        error_message: Optional[str] = None
    ):
        """작업 상태 업데이트"""
        job = self.get_job(job_id)
        if job:
            job.status = status
            if result is not None:
                job.result = result
            if error_message is not None:
                job.error_message = error_message
            self._save_jobs()
            logger.info(f"작업 상태 업데이트: {job_id} -> {status}")
        else:
            logger.warning(f"작업 없음: {job_id}")

    def get_all_jobs(self, status: Optional[str] = None) -> List[UploadJob]:
        """모든 작업 조회 (선택적 상태 필터)"""
        if status:
            return [job for job in self.jobs if job.status == status]
        return self.jobs

    def delete_job(self, job_id: str) -> bool:
        """작업 삭제"""
        job = self.get_job(job_id)
        if job and job.status in ['completed', 'failed']:
            self.jobs = [j for j in self.jobs if j.job_id != job_id]
            self._save_jobs()
            logger.info(f"작업 삭제: {job_id}")
            return True
        return False
