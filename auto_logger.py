# 완전 자동화 로거
# Obsidian 자동 기록 시스템

import functools
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable, Any
from obsidian_logger import ObsidianLogger


class AutoLogger:
    """완전 자동화 로거 - 데코레이터 및 컨텍스트 매니저"""

    def __init__(self):
        self.logger = ObsidianLogger()
        self.start_time = None
        self.task_name = None

    def function(self,
                 log_type: str = "feature",
                 description: Optional[str] = None,
                 log_args: bool = False,
                 log_result: bool = False):
        """
        함수 데코레이터 - 함수 실행 시 자동 기록

        사용법:
            @AutoLogger().function(log_type="feature", description="마진 계산")
            def calculate_margin(price, rate):
                return price * rate

        Args:
            log_type: "feature", "technical", "debug"
            description: 설명 (없으면 함수명 사용)
            log_args: 함수 인자 기록 여부
            log_result: 함수 결과 기록 여부
        """
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                func_name = func.__name__
                desc = description or f"{func_name} 실행"

                # 시작 시간
                start = time.time()

                # 인자 기록
                args_info = ""
                if log_args and (args or kwargs):
                    args_str = ", ".join(repr(a) for a in args)
                    kwargs_str = ", ".join(f"{k}={v!r}" for k, v in kwargs.items())
                    all_args = ", ".join(filter(None, [args_str, kwargs_str]))
                    args_info = f"\n\n**인자:** `{all_args}`"

                try:
                    # 함수 실행
                    result = func(*args, **kwargs)

                    # 실행 시간
                    elapsed = time.time() - start

                    # 결과 기록
                    result_info = ""
                    if log_result:
                        result_str = repr(result)
                        if len(result_str) > 100:
                            result_str = result_str[:100] + "..."
                        result_info = f"\n\n**결과:** `{result_str}`"

                    # Obsidian 기록
                    content = f"""
## {func_name}

{desc}

**실행 시간:** {elapsed:.3f}초{args_info}{result_info}

**상태:** ✅ 성공
"""

                    if log_type == "feature":
                        self.logger.log_to_daily(content, func_name)
                    elif log_type == "technical":
                        self.logger.log_to_daily(f"### {func_name}\n{content}", "기술 작업")
                    else:
                        self.logger.log_to_daily(content, "자동 기록")

                    return result

                except Exception as e:
                    # 에러 시간
                    elapsed = time.time() - start

                    # 에러 기록
                    error_content = f"""
## ❌ {func_name} 실행 실패

{desc}

**실행 시간:** {elapsed:.3f}초{args_info}

**에러:** `{type(e).__name__}: {str(e)}`

**상태:** ❌ 실패
"""
                    self.logger.log_to_daily(error_content, f"에러: {func_name}")
                    raise

            return wrapper
        return decorator

    def task(self, task_name: str, description: str = ""):
        """
        작업 블록 컨텍스트 매니저 - with 블록 자동 기록

        사용법:
            auto_logger = AutoLogger()

            with auto_logger.task("데이터 처리", "CSV 파일 처리 및 분석"):
                # 작업 코드
                process_data()
                analyze_results()
            # 자동으로 시작/종료 시간 기록
        """
        self.task_name = task_name
        self.task_description = description
        return self

    def __enter__(self):
        """작업 시작"""
        self.start_time = time.time()
        start_content = f"""
## 🚀 {self.task_name} 시작

{self.task_description}

**시작 시간:** {datetime.now().strftime('%H:%M:%S')}
"""
        self.logger.log_to_daily(start_content, self.task_name)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """작업 종료"""
        elapsed = time.time() - self.start_time

        if exc_type is None:
            # 성공
            end_content = f"""
## ✅ {self.task_name} 완료

**소요 시간:** {elapsed:.2f}초

**상태:** 성공
"""
        else:
            # 실패
            end_content = f"""
## ❌ {self.task_name} 실패

**소요 시간:** {elapsed:.2f}초

**에러:** `{exc_type.__name__}: {str(exc_val)}`

**상태:** 실패
"""

        self.logger.log_to_daily(end_content, f"{self.task_name} 종료")

        # False를 반환하면 예외 전파
        return False


# 글로벌 인스턴스 (편의성)
_auto_logger = AutoLogger()

# 편의 함수들
def auto_log(log_type: str = "feature", description: Optional[str] = None):
    """
    함수 자동 기록 데코레이터 (간단 버전)

    사용법:
        @auto_log("feature", "마진 계산 기능")
        def calculate_margin(price, rate):
            return price * rate
    """
    return _auto_logger.function(log_type=log_type, description=description)


def log_execution(description: Optional[str] = None, log_args: bool = True, log_result: bool = True):
    """
    함수 실행 상세 기록 데코레이터

    사용법:
        @log_execution("상세 마진 계산", log_args=True, log_result=True)
        def calculate_detailed_margin(price, rate, shipping):
            return price * rate - shipping
    """
    return _auto_logger.function(
        log_type="technical",
        description=description,
        log_args=log_args,
        log_result=log_result
    )


def task_context(task_name: str, description: str = ""):
    """
    작업 컨텍스트 매니저 (간단 버전)

    사용법:
        with task_context("CSV 생성", "전체 계정 CSV 생성"):
            generate_all_csvs()
    """
    return AutoLogger().task(task_name, description)


# 사용 예시
if __name__ == "__main__":
    # 예시 1: 함수 데코레이터 (간단)
    @auto_log("feature", "마진 계산 기능")
    def calculate_margin(price: int, rate: float) -> int:
        """마진 계산"""
        return int(price * (0.801 - rate) - 2000)

    # 예시 2: 함수 데코레이터 (상세)
    @log_execution("상세 마진 계산", log_args=True, log_result=True)
    def calculate_detailed_margin(price: int, rate: float, shipping: int = 2000) -> dict:
        """상세 마진 계산"""
        sale_price = int(price * 0.9)
        supply_cost = int(price * rate)
        margin = sale_price - supply_cost - shipping
        return {
            "sale_price": sale_price,
            "margin": margin
        }

    # 예시 3: 컨텍스트 매니저
    def process_books():
        """도서 처리"""
        with task_context("도서 처리", "알라딘 API에서 도서 검색 및 분석"):
            # 작업 1
            print("도서 검색 중...")
            time.sleep(0.5)

            # 작업 2
            print("마진 분석 중...")
            time.sleep(0.5)

            # 작업 3
            print("CSV 생성 중...")
            time.sleep(0.5)

    # 테스트 실행
    print("=== 자동 로깅 테스트 ===\n")

    print("1. 간단한 함수 실행:")
    result1 = calculate_margin(15000, 0.35)
    print(f"   결과: {result1}원\n")

    print("2. 상세 함수 실행:")
    result2 = calculate_detailed_margin(15000, 0.35, 2000)
    print(f"   결과: {result2}\n")

    print("3. 작업 블록 실행:")
    process_books()

    print("\n✅ 모든 작업이 Obsidian에 자동 기록되었습니다!")
    print("📁 확인: obsidian_vault/01-Daily/[오늘 날짜].md")
