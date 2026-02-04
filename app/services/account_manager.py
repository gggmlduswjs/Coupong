"""5개 계정 동시 관리 시스템"""
import asyncio
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import yaml
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import time
import random
import logging
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.account import Account
from uploaders.playwright_uploader import PlaywrightUploader

logger = logging.getLogger(__name__)


class AccountManager:
    """
    5개 계정 동시 관리 시스템
    - 순차 실행 (안전) 또는 제한적 병렬 실행
    - 계정별 상태 추적
    - 실패 재시도 로직
    """

    def __init__(self, config_path: str = "config/accounts.yaml"):
        self.config_path = Path(config_path)
        self.accounts_config = self._load_accounts_config()
        self.status_file = Path("data/status/account_status.json")
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        self.status = self._load_status()

    def _load_accounts_config(self) -> Dict:
        """계정 설정 로드"""
        if not self.config_path.exists():
            logger.warning(f"설정 파일 없음: {self.config_path}. 기본값 사용.")
            return {}
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get('accounts', {})

    def _load_status(self) -> Dict:
        """계정 상태 로드"""
        if self.status_file.exists():
            try:
                with open(self.status_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"상태 파일 로드 실패: {e}")
        return {}

    def _save_status(self):
        """계정 상태 저장"""
        try:
            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(self.status, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"상태 파일 저장 실패: {e}")

    def update_account_status(
        self, 
        account_id: str, 
        status: str, 
        details: Optional[Dict] = None
    ):
        """계정 상태 업데이트"""
        if account_id not in self.status:
            self.status[account_id] = {}

        self.status[account_id].update({
            'status': status,  # 'idle', 'running', 'completed', 'failed', 'paused'
            'last_update': datetime.now().isoformat(),
            'details': details or {}
        })
        self._save_status()

    def get_enabled_accounts(self) -> List[Tuple[str, Dict]]:
        """활성화된 계정 목록"""
        enabled = []
        for acc_id, acc_config in self.accounts_config.items():
            if acc_config.get('enabled', True):
                enabled.append((acc_id, acc_config))
        return enabled

    def get_account_from_db(self, account_name: str, db: Session) -> Optional[Account]:
        """DB에서 계정 정보 조회"""
        return db.query(Account).filter(Account.account_name == account_name).first()

    async def upload_to_single_account(
        self,
        account_id: str,
        account_config: Dict,
        products: List[Dict],
        dry_run: bool = True,
        db: Optional[Session] = None
    ) -> Dict:
        """단일 계정에 업로드"""
        self.update_account_status(account_id, 'running', {
            'total_products': len(products),
            'current_product': 0
        })

        try:
            # DB에서 계정 정보 가져오기
            account = None
            if db:
                account = self.get_account_from_db(account_id, db)
                if account:
                    email = account.email
                    # 비밀번호 복호화 필요 (추후 구현)
                    password = account_config.get('password', '')
                else:
                    # DB에 없으면 설정 파일에서 가져오기
                    email = account_config.get('email', '')
                    password = account_config.get('password', '')
            else:
                email = account_config.get('email', '')
                password = account_config.get('password', '')
            
            # 환경변수 처리
            import os
            if email.startswith('${') and email.endswith('}'):
                env_key = email[2:-1]
                email = os.getenv(env_key, email)
            if password.startswith('${') and password.endswith('}'):
                env_key = password[2:-1]
                password = os.getenv(env_key, password)

            if not email or not password:
                raise ValueError(f"계정 정보 불완전: {account_id}")

            # 업로더 생성
            account_db_id = account.id if (db and 'account' in locals() and account) else None
            uploader = PlaywrightUploader(
                account_id=account_db_id or 0,
                session_dir="sessions"
            )

            # 로그인
            login_success = await uploader.login(email, password)
            if not login_success:
                raise Exception("로그인 실패")

            success_count = 0
            failed_products = []

            for i, product in enumerate(products, 1):
                self.update_account_status(account_id, 'running', {
                    'total_products': len(products),
                    'current_product': i,
                    'current_product_name': product.get('product_name', product.get('name', ''))
                })

                if dry_run:
                    logger.info(f"[드라이런] {account_id}: {product.get('product_name', '')} 등록 시뮬레이션")
                    success_count += 1
                    await asyncio.sleep(1)  # 시뮬레이션 딜레이
                else:
                    # 실제 업로드
                    result = await uploader.upload_product(product)
                    if result.get('success'):
                        success_count += 1
                    else:
                        failed_products.append({
                            'product': product.get('product_name', ''),
                            'error': result.get('message', 'Unknown error')
                        })

                # 상품 간 딜레이
                delay = account_config.get('delay_between_products', 15)
                await asyncio.sleep(delay)

            # 결과 저장
            self.update_account_status(account_id, 'completed', {
                'success_count': success_count,
                'failed_count': len(failed_products),
                'failed_products': failed_products
            })

            return {
                'account_id': account_id,
                'success': True,
                'success_count': success_count,
                'failed_count': len(failed_products),
                'failed_products': failed_products
            }

        except Exception as e:
            logger.error(f"계정 {account_id} 업로드 실패: {e}", exc_info=True)
            self.update_account_status(account_id, 'failed', {
                'error': str(e)
            })
            return {
                'account_id': account_id,
                'success': False,
                'error': str(e)
            }

    async def upload_to_all_accounts_sequential(
        self,
        products: List[Dict],
        dry_run: bool = True,
        db: Optional[Session] = None
    ) -> List[Dict]:
        """
        모든 계정에 순차 업로드 (가장 안전)
        계정1 완료 → 계정2 → 계정3 ...
        """
        enabled_accounts = self.get_enabled_accounts()
        results = []

        for account_id, account_config in enabled_accounts:
            logger.info(f"\n{'='*60}")
            logger.info(f"계정 {account_id} 업로드 시작...")
            logger.info(f"{'='*60}\n")

            result = await self.upload_to_single_account(
                account_id,
                account_config,
                products,
                dry_run,
                db
            )
            results.append(result)

            # 계정 간 딜레이
            if account_id != enabled_accounts[-1][0]:  # 마지막 계정이 아니면
                delay = account_config.get('delay_between_accounts', 60)
                logger.info(f"\n계정 간 휴식: {delay}초 대기...\n")
                await asyncio.sleep(delay)

        return results

    async def upload_to_all_accounts_parallel(
        self,
        products: List[Dict],
        dry_run: bool = True,
        max_workers: int = 2,
        db: Optional[Session] = None
    ) -> List[Dict]:
        """
        제한적 병렬 업로드 (위험도 높음)
        max_workers=2: 최대 2개 계정만 동시 실행
        """
        enabled_accounts = self.get_enabled_accounts()
        results = []

        async def upload_account(acc_id: str, acc_config: Dict):
            return await self.upload_to_single_account(
                acc_id, acc_config, products, dry_run, db
            )

        # 병렬 실행
        tasks = [
            upload_account(acc_id, acc_config)
            for acc_id, acc_config in enabled_accounts
        ]

        # 최대 max_workers 개씩 실행
        semaphore = asyncio.Semaphore(max_workers)
        
        async def bounded_upload(acc_id: str, acc_config: Dict):
            async with semaphore:
                return await upload_account(acc_id, acc_config)

        bounded_tasks = [
            bounded_upload(acc_id, acc_config)
            for acc_id, acc_config in enabled_accounts
        ]

        results = await asyncio.gather(*bounded_tasks, return_exceptions=True)

        # 예외 처리
        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                acc_id = enabled_accounts[i][0]
                processed_results.append({
                    'account_id': acc_id,
                    'success': False,
                    'error': str(result)
                })
            else:
                processed_results.append(result)

        return processed_results

    def get_account_status_summary(self) -> Dict:
        """모든 계정 상태 요약"""
        summary = {
            'total_accounts': len(self.accounts_config),
            'enabled_accounts': len(self.get_enabled_accounts()),
            'accounts': {}
        }

        for account_id in self.accounts_config.keys():
            status = self.status.get(account_id, {})
            summary['accounts'][account_id] = {
                'status': status.get('status', 'idle'),
                'last_update': status.get('last_update'),
                'details': status.get('details', {})
            }

        return summary
