"""
재시도 로직 모듈
================
네트워크 오류, Rate Limit 등에 대한 지수 백오프 재시도

사용법:
    @retry_on_exception(max_attempts=3, base_delay=1.0)
    def api_call():
        return requests.get(url)

    # 또는 설정 객체로
    config = RetryConfig(max_attempts=5, base_delay=2.0)
    @retry_on_exception(config=config)
    def another_api_call():
        ...
"""
import time
import logging
import functools
from dataclasses import dataclass, field
from typing import Tuple, Type, Callable, Optional, Any

import requests

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """재시도 설정"""
    max_attempts: int = 3
    base_delay: float = 1.0  # 초
    max_delay: float = 30.0  # 최대 대기 시간 (초)
    exponential_base: float = 2.0  # 지수 배율
    jitter: bool = True  # 랜덤 지터 추가
    retryable_exceptions: Tuple[Type[Exception], ...] = field(
        default_factory=lambda: (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        )
    )
    retryable_status_codes: Tuple[int, ...] = (429, 500, 502, 503, 504)


# 기본 설정
DEFAULT_RETRY_CONFIG = RetryConfig()


def retry_on_exception(
    max_attempts: int = None,
    base_delay: float = None,
    config: RetryConfig = None,
    retryable_exceptions: Tuple[Type[Exception], ...] = None,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
):
    """
    재시도 데코레이터

    Args:
        max_attempts: 최대 시도 횟수 (None이면 config 또는 기본값 사용)
        base_delay: 기본 대기 시간 (초)
        config: RetryConfig 객체 (개별 인자보다 우선)
        retryable_exceptions: 재시도할 예외 튜플
        on_retry: 재시도 시 호출할 콜백 (exception, attempt)

    Returns:
        데코레이터 함수

    Example:
        @retry_on_exception(max_attempts=3, base_delay=1.0)
        def fetch_data():
            return requests.get("https://api.example.com/data")
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            # 설정 결정
            cfg = config or DEFAULT_RETRY_CONFIG
            _max_attempts = max_attempts if max_attempts is not None else cfg.max_attempts
            _base_delay = base_delay if base_delay is not None else cfg.base_delay
            _exceptions = retryable_exceptions or cfg.retryable_exceptions

            last_exception = None

            for attempt in range(1, _max_attempts + 1):
                try:
                    result = func(*args, **kwargs)

                    # requests.Response인 경우 상태 코드 확인
                    if hasattr(result, 'status_code'):
                        if result.status_code in cfg.retryable_status_codes:
                            if attempt < _max_attempts:
                                delay = _calculate_delay(
                                    attempt, _base_delay, cfg.max_delay,
                                    cfg.exponential_base, cfg.jitter
                                )
                                logger.warning(
                                    f"재시도 가능 상태 코드 {result.status_code}, "
                                    f"{delay:.2f}초 후 재시도 ({attempt}/{_max_attempts})"
                                )
                                time.sleep(delay)
                                continue

                    return result

                except _exceptions as e:
                    last_exception = e

                    if attempt < _max_attempts:
                        delay = _calculate_delay(
                            attempt, _base_delay, cfg.max_delay,
                            cfg.exponential_base, cfg.jitter
                        )
                        logger.warning(
                            f"오류 발생: {type(e).__name__}: {e}, "
                            f"{delay:.2f}초 후 재시도 ({attempt}/{_max_attempts})"
                        )

                        if on_retry:
                            on_retry(e, attempt)

                        time.sleep(delay)
                    else:
                        logger.error(f"최대 재시도 횟수 초과: {e}")
                        raise

            # 여기 도달하면 상태 코드로 인한 재시도 소진
            if last_exception:
                raise last_exception
            return result

        return wrapper
    return decorator


def _calculate_delay(
    attempt: int,
    base_delay: float,
    max_delay: float,
    exponential_base: float,
    jitter: bool,
) -> float:
    """지수 백오프 대기 시간 계산"""
    import random

    delay = base_delay * (exponential_base ** (attempt - 1))
    delay = min(delay, max_delay)

    if jitter:
        # ±25% 랜덤 지터
        jitter_range = delay * 0.25
        delay = delay + random.uniform(-jitter_range, jitter_range)

    return max(0.1, delay)  # 최소 0.1초


class RetryableError(Exception):
    """재시도 가능한 오류임을 명시하는 예외"""
    pass


def with_retry(
    func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    **kwargs
) -> Any:
    """
    함수형 재시도 래퍼 (데코레이터 없이 사용)

    Args:
        func: 실행할 함수
        *args: 함수 인자
        max_attempts: 최대 시도 횟수
        base_delay: 기본 대기 시간
        **kwargs: 함수 키워드 인자

    Returns:
        함수 실행 결과

    Example:
        result = with_retry(requests.get, "https://api.example.com", max_attempts=5)
    """
    @retry_on_exception(max_attempts=max_attempts, base_delay=base_delay)
    def _inner():
        return func(*args, **kwargs)

    return _inner()
