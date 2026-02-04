"""Obsidian 로깅을 사용한 개발 예시"""
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from obsidian_logger import ObsidianLogger


def example_feature_development():
    """새 기능 개발 예시"""
    logger = ObsidianLogger()

    # 1. 기능 개발 시작
    logger.log_to_daily("새로운 기능 개발 시작!", "개발 시작")

    logger.log_feature(
        "계정별 판매 통계",
        """
        5개 계정의 판매 현황을 비교 분석하는 기능

        ## 요구사항
        - 계정별 총 판매액
        - 계정별 판매 권수
        - 계정별 평균 마진
        - 시각화 (막대 그래프)

        ## 예상 소요 시간
        2-3 시간
        """,
        tags=["feature", "statistics", "dashboard"],
        status="진행중"
    )

    # 2. 개발 중 로그
    logger.log_to_daily("""
    **작업 내역:**
    - Sales 모델에서 데이터 조회 쿼리 작성
    - 계정별 집계 로직 구현
    - 테스트 케이스 작성
    """)

    # 3. 의사결정 기록
    logger.log_decision(
        "통계 계산 방식",
        context="""
        계정별 통계를 계산할 때 두 가지 방식 고려:
        1. 매번 DB에서 실시간 계산
        2. 일일 배치로 미리 계산하여 캐싱
        """,
        decision="""
        **선택:** 실시간 계산

        **이유:**
        - 현재 데이터 양이 적음 (월 60건)
        - 실시간 정확도가 중요
        - 캐싱 구조 복잡도 증가
        - 나중에 필요하면 최적화 가능
        """,
        alternatives=[
            "일일 배치 + Redis 캐싱",
            "Materialized View 사용"
        ]
    )

    # 4. 기술 문서 작성
    logger.log_technical(
        "계정별 통계 쿼리",
        """
        ## SQL 쿼리

        ```python
        stats = db.query(
            Listing.account_id,
            func.count(Sales.id).label('count'),
            func.sum(Sales.revenue).label('total_revenue'),
            func.avg(Sales.profit).label('avg_profit')
        ).join(Sales).group_by(Listing.account_id).all()
        ```

        ## 성능

        - 인덱스: account_id, sale_date
        - 평균 실행 시간: 10ms
        - 최적화: 필요 시 인덱스 추가

        ## 테스트

        ```python
        def test_account_statistics():
            stats = get_account_statistics()
            assert len(stats) == 5  # 5개 계정
            assert all(s['count'] >= 0 for s in stats)
        ```
        """,
        tags=["technical", "query", "statistics"]
    )

    # 5. 버그 발견 및 수정
    logger.log_bug(
        "계정 통계 0 division 오류",
        """
        **증상:**
        판매가 없는 계정의 평균 마진 계산 시 ZeroDivisionError

        **재현:**
        1. 새 계정 추가
        2. 판매 데이터 없음
        3. 통계 조회 시 오류
        """,
        solution="""
        **해결:**
        ```python
        avg_profit = (total_profit / count) if count > 0 else 0
        ```

        **테스트 추가:**
        ```python
        def test_account_with_no_sales():
            stats = get_account_statistics(account_id=999)
            assert stats['avg_profit'] == 0
        ```
        """
    )

    # 6. 완료
    logger.log_to_daily("""
    ## 계정별 판매 통계 기능 완료 ✅

    **구현 완료:**
    - ✅ 데이터 조회 쿼리
    - ✅ 집계 로직
    - ✅ 0 division 버그 수정
    - ✅ 테스트 케이스 작성
    - ✅ 문서화

    **다음 작업:**
    - 시각화 구현 (막대 그래프)
    - 대시보드에 통합
    """, "✅ 기능 완료")

    logger.log_feature(
        "계정별 판매 통계",
        "구현 및 테스트 완료",
        status="완료"
    )

    print("\n✅ Obsidian 로깅 예시 완료!")
    print(f"확인: {logger.vault}/01-Daily/{logger.get_daily_note_path().name}")


def example_daily_workflow():
    """하루 워크플로우 예시"""
    logger = ObsidianLogger()

    # 아침: 계획
    logger.log_to_daily("""
    ## 오늘의 목표 🎯

    ### 필수 작업
    - [ ] 마진 계산기 버그 수정
    - [ ] 묶음 SKU 테스트 작성
    - [ ] CSV 생성기 리팩토링

    ### 선택 작업
    - [ ] 문서 업데이트
    - [ ] 코드 리뷰

    ### 예상 소요 시간
    6시간
    """, "오늘의 계획")

    # 오전: 작업 1
    logger.log_to_daily("마진 계산기 버그 수정 시작")

    # 점심 후: 작업 2
    logger.log_to_daily("묶음 SKU 테스트 작성 시작")

    # 오후: 작업 3
    logger.log_to_daily("CSV 생성기 리팩토링 시작")

    # 저녁: 회고
    logger.log_to_daily("""
    ## 오늘의 회고 📝

    ### 완료 ✅
    - 마진 계산기 버그 수정 (순마진 계산 오류 수정)
    - 묶음 SKU 테스트 10개 작성 (커버리지 85%)
    - CSV 생성기 리팩토링 (200줄 → 150줄)

    ### 어려웠던 점 😓
    - CSV 생성기 리팩토링 시 예상보다 시간 소요
    - 기존 코드 의존성 복잡

    ### 배운 것 💡
    - 테스트 먼저 작성하면 리팩토링이 안전
    - 작은 단위로 커밋하는 것이 중요

    ### 내일 할 일 📅
    - CSV 생성기 성능 테스트
    - 대시보드 프로토타입 시작
    - 문서 업데이트
    """, "일일 회고")

    print("\n✅ 일일 워크플로우 로깅 완료!")


if __name__ == "__main__":
    print("\n" + "="*60)
    print("Obsidian 로깅 예시")
    print("="*60)

    print("\n1. 기능 개발 워크플로우 예시")
    example_feature_development()

    print("\n2. 일일 워크플로우 예시")
    example_daily_workflow()

    print("\n" + "="*60)
    print("Obsidian Vault에서 확인하세요!")
    print("="*60)
    print("\n위치: obsidian_vault/01-Daily/")
