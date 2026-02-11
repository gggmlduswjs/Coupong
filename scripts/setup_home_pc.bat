@echo off
chcp 65001 >nul
echo ============================================
echo   Coupong 집 PC 초기 설정 스크립트
echo ============================================
echo.

:: 1. Git pull
echo [1/5] 최신 코드 가져오기...
git pull
if %ERRORLEVEL% NEQ 0 (
    echo [오류] git pull 실패. 수동으로 확인하세요.
    pause
    exit /b 1
)
echo      완료!
echo.

:: 2. psycopg2-binary 설치
echo [2/5] PostgreSQL 드라이버 설치...
pip install psycopg2-binary
echo      완료!
echo.

:: 3. .env DATABASE_URL 변경
echo [3/5] .env DATABASE_URL → Supabase PostgreSQL...
python -c "
import re
with open('.env', 'r', encoding='utf-8') as f:
    content = f.read()
old = re.search(r'^DATABASE_URL=.*$', content, re.MULTILINE)
if old:
    new_url = 'DATABASE_URL=postgresql://postgres.glivxzmrgypqhtryoglg:0864gmldus!@aws-1-ap-south-1.pooler.supabase.com:6543/postgres'
    content = content[:old.start()] + new_url + content[old.end():]
    with open('.env', 'w', encoding='utf-8') as f:
        f.write(content)
    print('     DATABASE_URL 변경 완료')
else:
    print('     [경고] DATABASE_URL을 찾을 수 없습니다. .env를 확인하세요.')
"
echo.

:: 4. DB 연결 테스트
echo [4/5] Supabase 연결 테스트...
python -c "
from urllib.parse import quote
from sqlalchemy import create_engine, text
pw = quote('0864gmldus!', safe='')
url = f'postgresql://postgres.glivxzmrgypqhtryoglg:{pw}@aws-1-ap-south-1.pooler.supabase.com:6543/postgres'
eng = create_engine(url, pool_pre_ping=True, connect_args={'connect_timeout': 10})
with eng.connect() as c:
    cnt = c.execute(text(\"SELECT count(*) FROM listings\")).scalar()
    print(f'     연결 성공! listings: {cnt}행')
"
if %ERRORLEVEL% NEQ 0 (
    echo [오류] DB 연결 실패. 네트워크를 확인하세요.
    pause
    exit /b 1
)
echo.

:: 5. Tailscale serve 설정
echo [5/5] Tailscale serve 설정 (8503 프록시)...
where tailscale >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    if exist "C:\Program Files\Tailscale\tailscale.exe" (
        set TAILSCALE="C:\Program Files\Tailscale\tailscale.exe"
    ) else (
        echo      Tailscale 미설치. 설치합니다...
        winget install Tailscale.Tailscale --accept-package-agreements --accept-source-agreements
        set TAILSCALE="C:\Program Files\Tailscale\tailscale.exe"
    )
) else (
    set TAILSCALE=tailscale
)

%TAILSCALE% status >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo      Tailscale 로그인이 필요합니다.
    echo      트레이 아이콘에서 Log in 하거나 아래 명령어를 실행하세요:
    echo        %TAILSCALE% up
    echo.
    start "" "C:\Program Files\Tailscale\tailscale-ipn.exe"
    echo      로그인 후 아래 명령어를 수동 실행하세요:
    echo        %TAILSCALE% serve --https=443 off
    echo        %TAILSCALE% serve --bg --https=443 http://localhost:8503
) else (
    %TAILSCALE% serve --https=443 off >nul 2>nul
    %TAILSCALE% serve --bg --https=443 http://localhost:8503
    echo      완료!
)
echo.

echo ============================================
echo   설정 완료! 대시보드 실행:
echo     streamlit run dashboard.py
echo ============================================
pause
