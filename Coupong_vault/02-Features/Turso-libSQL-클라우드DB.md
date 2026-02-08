# Turso(libSQL) 클라우드 DB 지원

#feature #database #turso #deployment

**상태:** ✅ 완료
**구현 파일:** `app/database.py`

---

## 개요
Streamlit Cloud 배포를 위해 로컬 SQLite DB를 Turso(libSQL) 클라우드 DB로 전환 가능하도록 엔진 팩토리를 중앙화. 환경에 따라 로컬 SQLite / Turso를 자동 분기.

## 구현 파일
- `app/database.py` — 엔진 팩토리 (`_resolve_database_url()`, `_create_engine_for_url()`, `get_engine_for_db()`)
- `app/config.py` — `turso_database_url`, `turso_auth_token` 설정 추가
- `scripts/migrate_to_turso.py` — WAL 체크포인트 + Turso CLI 업로드 도우미

## 핵심 로직
1. URL 결정 우선순위: `DATABASE_URL` 환경변수 → Streamlit secrets (`[turso]`) → `app/config.py` Turso 설정 → 로컬 SQLite
2. 로컬 SQLite: `check_same_thread=False`, `timeout=30`, WAL 모드 + busy_timeout PRAGMA
3. Turso: connect_args 없음, PRAGMA 스킵, authToken 쿼리 파라미터로 인증

## 배포 구조
```
로컬: dashboard.py / scripts/*.py → app/database.py → SQLite (./coupang_auto.db)
클라우드: dashboard.py → app/database.py → Turso (libsql://xxx.turso.io)
```

## 사용법
```bash
# 마이그레이션
python scripts/migrate_to_turso.py

# Streamlit Cloud Secrets
[turso]
database_url = "libsql://coupang-auto-xxx.turso.io"
auth_token = "eyJhbGci..."
```

## 관련 문서
- [[2026-02-08]] - 구현 일일 로그
