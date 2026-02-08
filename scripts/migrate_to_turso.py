"""
로컬 SQLite → Turso(libSQL) 마이그레이션 (REST API 방식)
=========================================================
turso CLI 없이 Platform REST API로 직접 업로드

사용법:
    python scripts/migrate_to_turso.py                    # 전체 마이그레이션
    python scripts/migrate_to_turso.py --db-name my-db    # DB 이름 지정
    python scripts/migrate_to_turso.py --checkpoint-only  # WAL 체크포인트만

필요 환경변수 (.env):
    TURSO_API_TOKEN=your_platform_api_token
"""
import os
import sys
import argparse
import sqlite3
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

ROOT = Path(__file__).parent.parent
DB_PATH = ROOT / "coupang_auto.db"
TURSO_API_BASE = "https://api.turso.tech/v1"


def load_env():
    """Load .env file"""
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, _, value = line.partition('=')
                os.environ.setdefault(key.strip(), value.strip())


def api_request(method, path, token, data=None, binary=False):
    """Turso Platform API 호출"""
    url = f"{TURSO_API_BASE}{path}" if path.startswith("/") else path
    headers = {"Authorization": f"Bearer {token}"}

    if binary:
        headers["Content-Type"] = "application/octet-stream"
        body = data
    elif data is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(data).encode('utf-8')
    else:
        body = None

    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except HTTPError as e:
        error_body = e.read().decode('utf-8')
        try:
            error_json = json.loads(error_body)
            return {"error": error_json.get("error", error_body), "status": e.code}
        except json.JSONDecodeError:
            return {"error": error_body, "status": e.code}


def wal_checkpoint(db_path: Path):
    """WAL 체크포인트 실행 — 변경사항을 메인 DB 파일에 기록"""
    print(f"[1/5] WAL 체크포인트 실행: {db_path}")
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # WAL 모드 확인 및 설정
    cursor.execute("PRAGMA journal_mode;")
    mode = cursor.fetchone()[0]
    print(f"  현재 journal_mode: {mode}")

    if mode != 'wal':
        cursor.execute("PRAGMA journal_mode=wal;")
        print("  → WAL 모드로 변경")

    # 체크포인트 실행
    cursor.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    result = cursor.fetchone()
    conn.close()
    print(f"  결과: busy={result[0]}, log={result[1]}, checkpointed={result[2]}")

    if result[0] != 0:
        print("  ⚠ DB가 사용 중입니다. 다른 프로세스를 종료 후 재시도하세요.")
        return False

    print("  ✓ 체크포인트 완료")
    return True


def get_org_slug(token):
    """Turso 조직(organization) slug 조회"""
    print("\n[2/5] Turso 계정 확인")
    result = api_request("GET", "/organizations", token)

    if "error" in result:
        print(f"  ✗ API 토큰 인증 실패: {result['error']}")
        return None

    if isinstance(result, list) and len(result) > 0:
        org = result[0]
        slug = org.get("slug", org.get("name", ""))
        print(f"  ✓ 조직: {slug} (type: {org.get('type', 'personal')})")
        return slug

    print("  ✗ 조직 정보를 찾을 수 없습니다.")
    return None


def create_database(token, org_slug, db_name):
    """Turso DB 생성 (database_upload 시드)"""
    print(f"\n[3/5] Turso DB 생성: {db_name}")

    # 먼저 기존 DB 확인
    existing = api_request("GET", f"/organizations/{org_slug}/databases", token)
    if isinstance(existing, dict) and "databases" in existing:
        for db in existing["databases"]:
            if db.get("Name") == db_name or db.get("name") == db_name:
                print(f"  ⚠ '{db_name}' DB가 이미 존재합니다.")
                hostname = db.get("Hostname") or db.get("hostname", "")
                print(f"  Hostname: {hostname}")
                return hostname

    # DB 생성 (upload 시드)
    data = {
        "name": db_name,
        "group": "default",
        "seed": {"type": "database_upload"}
    }
    result = api_request("POST", f"/organizations/{org_slug}/databases", token, data)

    if "error" in result:
        print(f"  ✗ DB 생성 실패: {result['error']}")
        return None

    db_info = result.get("database", result)
    hostname = db_info.get("Hostname") or db_info.get("hostname", "")
    print(f"  ✓ DB 생성 완료")
    print(f"  Hostname: {hostname}")
    return hostname


def create_db_token(token, org_slug, db_name):
    """DB 인증 토큰 생성"""
    print(f"\n[4/5] DB 인증 토큰 생성")

    result = api_request(
        "POST",
        f"/organizations/{org_slug}/databases/{db_name}/auth/tokens",
        token,
        {"authorization": "full-access"}
    )

    if "error" in result:
        print(f"  ✗ 토큰 생성 실패: {result['error']}")
        return None

    jwt = result.get("jwt", "")
    if jwt:
        print(f"  ✓ 토큰 생성 완료: {jwt[:20]}...{jwt[-10:]}")
    return jwt


def upload_database(hostname, db_token, db_path: Path):
    """SQLite 파일을 Turso에 업로드"""
    file_size = db_path.stat().st_size
    size_mb = file_size / 1024 / 1024
    print(f"\n[5/5] DB 파일 업로드: {size_mb:.1f} MB")
    print(f"  대상: https://{hostname}/v1/upload")

    # 파일 읽기
    with open(db_path, 'rb') as f:
        file_data = f.read()

    print(f"  업로드 중... ({len(file_data):,} bytes)")
    start = time.time()

    url = f"https://{hostname}/v1/upload"
    headers = {
        "Authorization": f"Bearer {db_token}",
        "Content-Type": "application/octet-stream",
    }
    req = Request(url, data=file_data, headers=headers, method="POST")

    try:
        with urlopen(req, timeout=600) as resp:
            elapsed = time.time() - start
            result = resp.read().decode('utf-8')
            print(f"  ✓ 업로드 완료! ({elapsed:.1f}초, {size_mb / elapsed:.1f} MB/s)")
            if result.strip():
                print(f"  응답: {result[:200]}")
            return True
    except HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"  ✗ 업로드 실패 (HTTP {e.code}): {error_body[:300]}")
        return False
    except Exception as e:
        print(f"  ✗ 업로드 실패: {e}")
        return False


def show_result(hostname, db_token, db_name):
    """결과 출력 — Streamlit Cloud 설정 안내"""
    db_url = f"libsql://{hostname}"

    print(f"\n{'=' * 60}")
    print("✓ 마이그레이션 완료!")
    print(f"{'=' * 60}")

    print(f"\n■ Turso DB 정보:")
    print(f"  Database: {db_name}")
    print(f"  URL: {db_url}")
    print(f"  Token: {db_token[:20]}...{db_token[-10:]}")

    print(f"\n■ Streamlit Cloud Secrets (.streamlit/secrets.toml):")
    print(f"{'─' * 60}")
    print(f'[turso]')
    print(f'database_url = "{db_url}"')
    print(f'auth_token = "{db_token}"')
    print(f"{'─' * 60}")

    print(f"\n■ .env 추가 (로컬 테스트용):")
    print(f"TURSO_DATABASE_URL={db_url}")
    print(f"TURSO_AUTH_TOKEN={db_token}")

    # secrets.toml 자동 생성
    secrets_dir = ROOT / ".streamlit"
    secrets_dir.mkdir(exist_ok=True)
    secrets_path = secrets_dir / "secrets.toml"
    secrets_content = f"""[turso]
database_url = "{db_url}"
auth_token = "{db_token}"
"""
    secrets_path.write_text(secrets_content, encoding='utf-8')
    print(f"\n✓ {secrets_path} 자동 생성 완료")


def main():
    parser = argparse.ArgumentParser(description="로컬 SQLite → Turso 마이그레이션 (REST API)")
    parser.add_argument("--db-path", default=str(DB_PATH), help="로컬 DB 파일 경로")
    parser.add_argument("--db-name", default="coupang-auto", help="Turso DB 이름")
    parser.add_argument("--checkpoint-only", action="store_true", help="WAL 체크포인트만 실행")
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"DB 파일을 찾을 수 없습니다: {db_path}")
        sys.exit(1)

    # 환경변수 로드
    load_env()

    # 1. WAL 체크포인트
    if not wal_checkpoint(db_path):
        sys.exit(1)

    if args.checkpoint_only:
        print("\n체크포인트 완료. --checkpoint-only 모드이므로 종료합니다.")
        return

    # API 토큰 확인
    api_token = os.environ.get("TURSO_API_TOKEN", "")
    if not api_token:
        print("\n✗ TURSO_API_TOKEN이 설정되지 않았습니다.")
        print("  .env 파일에 추가하세요: TURSO_API_TOKEN=your_token")
        print("  토큰 발급: https://turso.tech/app → Settings → API Tokens")
        sys.exit(1)

    # 2. 조직 slug 조회
    org_slug = get_org_slug(api_token)
    if not org_slug:
        sys.exit(1)

    # 3. DB 생성
    hostname = create_database(api_token, org_slug, args.db_name)
    if not hostname:
        sys.exit(1)

    # 4. DB 토큰 생성
    db_token = create_db_token(api_token, org_slug, args.db_name)
    if not db_token:
        sys.exit(1)

    # 5. 파일 업로드
    if not upload_database(hostname, db_token, db_path):
        sys.exit(1)

    # 결과 출력
    show_result(hostname, db_token, args.db_name)


if __name__ == "__main__":
    main()
