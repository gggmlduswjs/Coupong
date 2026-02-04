"""통합 업로더 서비스 - 5개 계정 관리"""
import asyncio
from typing import List, Dict, Optional
import logging
from sqlalchemy.orm import Session

from app.services.account_manager import AccountManager
from app.services.job_queue import JobQueue, UploadJob
from app.database import get_db

logger = logging.getLogger(__name__)


class UploaderService:
    """통합 업로더 서비스"""

    def __init__(self):
        self.account_manager = AccountManager()
        self.job_queue = JobQueue()

    async def create_upload_job(
        self,
        account_ids: List[str],
        products: List[Dict],
        priority: int = 1,
        dry_run: bool = True,
        execution_mode: str = 'sequential',
        max_workers: int = 2
    ) -> str:
        """업로드 작업 생성"""
        job_id = self.job_queue.add_job(
            account_ids=account_ids,
            products=products,
            priority=priority,
            dry_run=dry_run,
            execution_mode=execution_mode,
            max_workers=max_workers
        )
        return job_id

    async def execute_job(
        self,
        job_id: str,
        db: Optional[Session] = None
    ) -> Dict:
        """작업 실행"""
        job = self.job_queue.get_job(job_id)
        if not job:
            raise ValueError(f"작업 없음: {job_id}")

        if job.status != 'pending':
            raise ValueError(f"작업이 이미 실행됨: {job.status}")

        # 상태 업데이트
        self.job_queue.update_job_status(job_id, 'running')

        try:
            # 실행 모드에 따라 분기
            if job.execution_mode == 'sequential':
                results = await self.account_manager.upload_to_all_accounts_sequential(
                    products=job.products,
                    dry_run=job.dry_run,
                    db=db
                )
            else:
                results = await self.account_manager.upload_to_all_accounts_parallel(
                    products=job.products,
                    dry_run=job.dry_run,
                    max_workers=job.max_workers,
                    db=db
                )

            # 결과 집계
            total_success = sum(1 for r in results if r.get('success'))
            total_failed = len(results) - total_success

            result_summary = {
                'total_accounts': len(results),
                'success_count': total_success,
                'failed_count': total_failed,
                'results': results
            }

            # 작업 완료
            self.job_queue.update_job_status(
                job_id,
                'completed',
                result=result_summary
            )

            return result_summary

        except Exception as e:
            logger.error(f"작업 실행 실패: {job_id}", exc_info=True)
            self.job_queue.update_job_status(
                job_id,
                'failed',
                error_message=str(e)
            )
            raise

    async def upload_to_all_accounts(
        self,
        products: List[Dict],
        account_ids: Optional[List[str]] = None,
        dry_run: bool = True,
        execution_mode: str = 'sequential',
        max_workers: int = 2,
        db: Optional[Session] = None
    ) -> Dict:
        """
        모든 계정에 업로드 (간편 메서드)
        
        Args:
            products: 업로드할 상품 목록
            account_ids: 대상 계정 목록 (None이면 모든 활성 계정)
            dry_run: 드라이런 모드
            execution_mode: 'sequential' or 'parallel'
            max_workers: 병렬 실행 시 최대 워커 수
            db: 데이터베이스 세션
        """
        # 계정 목록 결정
        if account_ids is None:
            enabled_accounts = self.account_manager.get_enabled_accounts()
            account_ids = [acc_id for acc_id, _ in enabled_accounts]

        # 작업 생성 및 실행
        job_id = await self.create_upload_job(
            account_ids=account_ids,
            products=products,
            dry_run=dry_run,
            execution_mode=execution_mode,
            max_workers=max_workers
        )

        return await self.execute_job(job_id, db=db)

    def get_job_status(self, job_id: str) -> Optional[Dict]:
        """작업 상태 조회"""
        job = self.job_queue.get_job(job_id)
        if not job:
            return None

        return {
            'job_id': job.job_id,
            'status': job.status,
            'account_ids': job.account_ids,
            'product_count': len(job.products),
            'created_at': job.created_at,
            'dry_run': job.dry_run,
            'execution_mode': job.execution_mode,
            'result': job.result,
            'error_message': job.error_message
        }

    def get_all_jobs(self, status: Optional[str] = None) -> List[Dict]:
        """모든 작업 목록 조회"""
        jobs = self.job_queue.get_all_jobs(status=status)
        return [job.to_dict() for job in jobs]

    def get_account_status(self) -> Dict:
        """계정 상태 조회"""
        return self.account_manager.get_account_status_summary()
