"""빠른 업로드 예시 스크립트"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.uploader_service import UploaderService

async def quick_example():
    """빠른 예시"""
    print("5개 계정 동시 업로드 예시\n")
    
    # 업로더 서비스 생성
    uploader_service = UploaderService()
    
    # 예시 상품 데이터
    products = [
        {
            "product_name": "초등 수학 문제집 3학년",
            "sale_price": 15000,
            "original_price": 15000,
            "isbn": "9781234567890",
            "description": "초등학교 3학년 수학 문제집입니다.",
            "main_image_url": "https://example.com/image.jpg"
        },
        {
            "product_name": "중학 영어 문법서",
            "sale_price": 18000,
            "original_price": 18000,
            "isbn": "9781234567891",
            "description": "중학교 영어 문법을 체계적으로 학습할 수 있는 교재입니다.",
            "main_image_url": "https://example.com/image2.jpg"
        }
    ]
    
    print(f"상품 수: {len(products)}개")
    print("드라이런 모드로 실행합니다...\n")
    
    # 드라이런 모드로 모든 계정에 업로드
    try:
        result = await uploader_service.upload_to_all_accounts(
            products=products,
            account_ids=None,  # 모든 활성 계정
            dry_run=True,  # 드라이런 모드
            execution_mode='sequential',  # 순차 실행
            max_workers=2
        )
        
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
                print(f"✅ {acc_id}: {account_result.get('success_count', 0)}개 성공")
            else:
                print(f"❌ {acc_id}: {account_result.get('error', 'Unknown')}")
        
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    print("="*60)
    print("빠른 업로드 예시")
    print("="*60)
    print("\n⚠️ 주의: 이 스크립트는 드라이런 모드로 실행됩니다.")
    print("실제 업로드를 하려면 dry_run=False로 변경하세요.\n")
    
    asyncio.run(quick_example())
