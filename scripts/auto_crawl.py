"""
자동 크롤링 스케줄러
====================
매일 새벽 3시에 전체 출판사 신간을 자동 크롤링 → 마진 분석 → 쿠팡 자동 등록
완전 자동화: 크롤링 → Product 생성 → 갭 분석 → 5개 계정 일괄 등록

사용법:
    python scripts/auto_crawl.py          # 데몬 모드 (새벽 3시 자동 실행)
    python scripts/auto_crawl.py --now    # 즉시 실행 (테스트용)
    python scripts/auto_crawl.py --hour 4 # 새벽 4시로 변경
"""
import sys
import os
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta

# 프로젝트 루트 설정
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
os.chdir(project_root)

from dotenv import load_dotenv
load_dotenv()

# 로그 디렉토리 생성
log_dir = project_root / "logs"
log_dir.mkdir(exist_ok=True)

# 로깅 설정: 콘솔 + 파일
log_formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d %H:%M:%S')

file_handler = logging.FileHandler(log_dir / "auto_crawl.log", encoding="utf-8")
file_handler.setFormatter(log_formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)

logger = logging.getLogger("auto_crawl")
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ─── 설정 ───
CRAWL_HOUR = 3          # 기본 실행 시각 (새벽 3시)
MAX_PER_PUBLISHER = 50   # 출판사당 최대 검색 수
YEAR_FILTER = 2025       # 2025년 이후 도서만
CHECK_INTERVAL = 30      # 시간 체크 간격 (초)
DB_TIMEOUT = 30          # SQLite timeout (대시보드 동시 접근 대비)


def log_to_obsidian(message: str, title: str = "자동 크롤링"):
    """Obsidian daily note에 결과 기록"""
    vault_dir = project_root / "Coupong_vault" / "01-Daily"
    if not vault_dir.exists():
        return

    today = datetime.now().strftime("%Y-%m-%d")
    daily_file = vault_dir / f"{today}.md"
    now_time = datetime.now().strftime("%H:%M")

    entry = f"\n## {now_time} - {title}\n\n{message}\n\n---\n"

    if daily_file.exists():
        with open(daily_file, "a", encoding="utf-8") as f:
            f.write(entry)
    else:
        header = f"# {datetime.now().strftime('%Y년 %m월 %d일')} 개발 로그\n\n## 오늘의 작업\n\n---\n"
        with open(daily_file, "w", encoding="utf-8") as f:
            f.write(header + entry)


def run_crawl():
    """크롤링 + 마진 분석 실행"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.config import settings
    from app.database import init_db
    from scripts.franchise_sync import FranchiseSync

    logger.info("=" * 60)
    logger.info("자동 크롤링 시작")
    logger.info("=" * 60)

    start_time = datetime.now()

    # DB timeout 설정 (대시보드 동시 접근 충돌 방지)
    db_url = settings.database_url
    connect_args = {"check_same_thread": False, "timeout": DB_TIMEOUT} if "sqlite" in db_url else {}
    engine = create_engine(db_url, connect_args=connect_args, echo=False)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()

    init_db()

    sync = FranchiseSync(db=db)

    try:
        # Step 1: 출판사별 키워드 검색 크롤링
        logger.info("[1/4] 출판사별 크롤링 (year_filter=%d, max=%d/출판사)", YEAR_FILTER, MAX_PER_PUBLISHER)
        crawl_result = sync.crawl_by_publisher(
            max_per_publisher=MAX_PER_PUBLISHER,
            year_filter=YEAR_FILTER,
        )
        logger.info(
            "크롤링 결과: 검색 %d개, 신규 %d개, 스킵 %d개",
            crawl_result["searched"], crawl_result["new"], crawl_result["skipped"]
        )

        # Step 2: 마진 분석 + Product 생성
        logger.info("[2/4] 마진 분석...")
        analyze_result = sync.analyze_products(crawl_result["books"])
        logger.info(
            "분석 결과: %d개 Product 생성, 묶음필요 %d개",
            analyze_result["created"], analyze_result["bundle_needed"]
        )

        # Step 3: 갭 분석 (계정별 미등록 도서)
        logger.info("[3/4] 갭 분석...")
        gaps = sync.find_gaps()
        total_missing = sum(g["missing"] for g in gaps.values())
        logger.info("갭 분석: %d개 계정, 총 미등록 %d개", len(gaps), total_missing)

        # Step 4: 계정별 자동 등록
        upload_results = {}
        if total_missing > 0:
            logger.info("[4/4] 계정별 자동 등록...")
            for acc_name, gap_info in gaps.items():
                if not gap_info["products"]:
                    upload_results[acc_name] = {"success": 0, "failed": 0, "skipped": True}
                    continue

                logger.info("  %s: 미등록 %d개 등록 시작", acc_name, len(gap_info["products"]))
                try:
                    result = sync.upload_to_account(
                        account=gap_info["account"],
                        products=gap_info["products"],
                        dry_run=False,
                    )
                    upload_results[acc_name] = {
                        "success": result["success"],
                        "failed": result["failed"],
                    }
                    logger.info("  %s: 성공 %d, 실패 %d", acc_name, result["success"], result["failed"])
                except Exception as upload_err:
                    logger.error("  %s: 등록 실패 — %s", acc_name, upload_err)
                    upload_results[acc_name] = {"success": 0, "failed": len(gap_info["products"]), "error": str(upload_err)}
        else:
            logger.info("[4/4] 미등록 도서 없음 — 등록 스킵")

        total_uploaded = sum(r.get("success", 0) for r in upload_results.values())
        total_failed = sum(r.get("failed", 0) for r in upload_results.values())

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info("완료! 소요시간: %.1f초", elapsed)

        # Obsidian 기록
        obsidian_lines = [
            f"- **검색**: {crawl_result['searched']}개 도서 검색",
            f"- **신규 도서**: {crawl_result['new']}개 발견",
            f"- **Product 생성**: {analyze_result['created']}개",
            f"- **미등록 갭**: {total_missing}개",
            f"- **쿠팡 등록**: 성공 {total_uploaded}개 / 실패 {total_failed}개",
        ]
        # 계정별 상세
        for acc_name, r in upload_results.items():
            if r.get("skipped"):
                continue
            obsidian_lines.append(f"  - {acc_name}: 성공 {r['success']}, 실패 {r['failed']}")
        obsidian_lines.append(f"- **소요시간**: {elapsed:.1f}초")
        log_to_obsidian("\n".join(obsidian_lines), "자동 크롤링+등록 완료")

        return {
            "success": True,
            "searched": crawl_result["searched"],
            "new_books": crawl_result["new"],
            "new_products": analyze_result["created"],
            "gaps": total_missing,
            "uploaded": total_uploaded,
            "upload_failed": total_failed,
            "elapsed": elapsed,
        }

    except Exception as e:
        logger.error("크롤링 실패: %s", e, exc_info=True)
        log_to_obsidian(f"- **에러**: `{e}`", "자동 크롤링 실패")
        return {"success": False, "error": str(e)}

    finally:
        sync.close()
        db.close()
        engine.dispose()


def run_daemon(crawl_hour: int):
    """데몬 모드: 매일 지정 시각에 크롤링 실행"""
    logger.info("자동 크롤링 데몬 시작 (매일 %02d:00 실행)", crawl_hour)
    log_to_obsidian(
        f"- **모드**: 데몬 (매일 {crawl_hour:02d}:00)\n- **PID**: {os.getpid()}",
        "자동 크롤링 데몬 시작"
    )

    ran_today = False

    while True:
        now = datetime.now()

        if now.hour == crawl_hour and not ran_today:
            logger.info("스케줄 시각 도달 — 크롤링 시작")
            run_crawl()
            ran_today = True

            # 다음 날까지 대기 (남은 시간 계산)
            tomorrow = (now + timedelta(days=1)).replace(
                hour=crawl_hour, minute=0, second=0, microsecond=0
            )
            wait_seconds = (tomorrow - datetime.now()).total_seconds()
            logger.info("다음 실행: %s (%.0f초 후)", tomorrow.strftime("%Y-%m-%d %H:%M"), wait_seconds)
            time.sleep(max(wait_seconds, 60))  # 최소 60초
            ran_today = False
        else:
            # 날짜가 바뀌면 리셋
            if now.hour != crawl_hour:
                ran_today = False
            time.sleep(CHECK_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="자동 크롤링 스케줄러")
    parser.add_argument("--now", action="store_true", help="즉시 실행 (테스트용)")
    parser.add_argument("--hour", type=int, default=CRAWL_HOUR, help=f"실행 시각 (기본: {CRAWL_HOUR}시)")
    args = parser.parse_args()

    if args.now:
        logger.info("즉시 실행 모드")
        result = run_crawl()
        if result["success"]:
            print(f"\n자동 크롤링+등록 완료!")
            print(f"  검색: {result['searched']}개")
            print(f"  신규 도서: {result['new_books']}개")
            print(f"  Product 생성: {result['new_products']}개")
            print(f"  미등록 갭: {result['gaps']}개")
            print(f"  쿠팡 등록: 성공 {result['uploaded']}개 / 실패 {result['upload_failed']}개")
            print(f"  소요시간: {result['elapsed']:.1f}초")
        else:
            print(f"\n크롤링 실패: {result['error']}")
            sys.exit(1)
    else:
        try:
            run_daemon(args.hour)
        except KeyboardInterrupt:
            logger.info("데몬 종료 (Ctrl+C)")
            log_to_obsidian("- 사용자에 의해 종료됨", "자동 크롤링 데몬 종료")


if __name__ == "__main__":
    main()
