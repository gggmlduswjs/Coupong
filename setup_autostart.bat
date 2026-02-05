@echo off
chcp 65001 >nul
echo 대시보드 자동 시작 등록 중...
schtasks /create /tn "CoupongDashboard" /tr "cmd /c cd /d C:\Users\MSI\Desktop\Coupong && C:\Users\MSI\AppData\Local\Programs\Python\Python310\Scripts\streamlit.exe run dashboard.py --server.address 0.0.0.0 --server.port 8501 --server.headless true" /sc onlogon /rl highest /f
if %errorlevel% equ 0 (
    echo [성공] 윈도우 로그인 시 자동 시작 등록 완료!
) else (
    echo [실패] 관리자 권한으로 다시 실행하세요.
)
pause
