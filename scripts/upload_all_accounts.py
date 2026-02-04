"""5개 계정 동시 업로드 실행 스크립트"""
import asyncio
import sys
import json
from pathlib import Path
from typing import List, Dict

# 프로젝트 루트를 경로에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.uploader_service import UploaderService
from app.database import get_db

def load_products_from_file(file_path: str) -> List[Dict]:
    """파일에서 상품 데이터 로드"""
    path = Path(file_path)
    
    if not path.exists():
        print(f"❌ 파일 없음: {file_path}")
        return []
    
    with open(path, 'r', encoding='utf-8') as f:
        if path.suffix == '.json':
            return json.load(f)
        else:
            print(f"❌ 지원하지 않는 파일 형식: {path.suffix}")
            return []

async def main():
    """메인 실행 함수"""
    print("="*60)
    print("쿠팡 5개 계정 동시 업로드 시스템")
    print("="*60)
    
    # 상품 데이터 로드
    products_file = Path("data/templates/products_to_upload.json")
    if not products_file.exists():
        print(f"\n❌ 상품 데이터 파일이 없습니다: {products_file}")
        print("다음 형식으로 파일을 생성해주세요:")
        print("""
[
  {
    "product_name": "상품명",
    "sale_price": 15000,
    "original_price": 15000,
    "isbn": "9781234567890",
    "description": "상품 설명",
    "main_image_url": "https://..."
  }
]
        """)
        return
    
    products = load_products_from_file(str(products_file))
    if not products:
        print("❌ 상품 데이터가 비어있습니다.")
        return
    
    print(f"\n✅ 상품 {len(products)}개 로드 완료")
    
    # 실행 모드 선택
    print("\n실행 모드를 선택하세요:")
    print("1. 순차 실행 (안전, 추천) - 계정1 → 계정2 → ...")
    print("2. 병렬 실행 (위험) - 최대 2개 계정 동시")
    print("3. 드라이런 테스트 (실제 등록 안 함)")
    
    mode = input("\n선택 (1/2/3): ").strip()
    
    if mode == "3":
        dry_run = True
        execution_mode = "sequential"
        print("\n⚠️ 드라이런 모드: 실제 등록은 하지 않습니다.")
    elif mode == "1":
        dry_run = False
        execution_mode = "sequential"
        print("\n✅ 순차 실행 모드")
    elif mode == "2":
        dry_run = False
        execution_mode = "parallel"
        print("\n⚠️ 병렬 실행 모드 (위험)")
    else:
        print("❌ 잘못된 선택")
        return
    
    # 계정 선택
    uploader_service = UploaderService()
    account_status = uploader_service.get_account_status()
    
    enabled_accounts = account_status['enabled_accounts']
    print(f"\n활성 계정: {enabled_accounts}개")
    
    use_all = input("모든 계정에 업로드하시겠습니까? (y/n): ").strip().lower()
    
    if use_all == 'y':
        account_ids = None  # 모든 계정
    else:
        print("\n업로드할 계정을 선택하세요 (쉼표로 구분, 예: account_01,account_02):")
        selected = input("계정 ID: ").strip()
        account_ids = [acc.strip() for acc in selected.split(',')]
    
    # 최종 확인
    print("\n" + "="*60)
    print("실행 정보")
    print("="*60)
    print(f"상품 수: {len(products)}개")
    print(f"대상 계정: {len(account_ids) if account_ids else enabled_accounts}개")
    if account_ids:
        for acc_id in account_ids:
            print(f"  - {acc_id}")
    print(f"드라이런: {dry_run}")
    print(f"실행 모드: {execution_mode}")
    print("="*60)
    
    confirm = input("\n계속하시겠습니까? (yes/no): ").strip().lower()
    if confirm != 'yes':
        print("취소되었습니다.")
        return
    
    # 실행
    print("\n업로드 시작...\n")
    
    try:
        db = next(get_db())
        result = await uploader_service.upload_to_all_accounts(
            products=products,
            account_ids=account_ids,
            dry_run=dry_run,
            execution_mode=execution_mode,
            max_workers=2,
            db=db
        )
        
        # 결과 출력
        print("\n" + "="*60)
        print("실행 결과")
        print("="*60)
        print(f"총 계정: {result['total_accounts']}개")
        print(f"성공: {result['success_count']}개")
        print(f"실패: {result['failed_count']}개")
        
        print("\n계정별 상세:")
        for account_result in result['results']:
            acc_id = account_result['account_id']
            if account_result.get('success'):
                print(f"✅ {acc_id}: {account_result.get('success_count', 0)}개 성공, "
                      f"{account_result.get('failed_count', 0)}개 실패")
            else:
                print(f"❌ {acc_id}: 실패 - {account_result.get('error', 'Unknown')}")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if 'db' in locals():
            db.close()

if __name__ == '__main__':
    asyncio.run(main())
