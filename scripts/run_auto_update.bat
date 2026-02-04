@echo off
REM 자동 업데이트 실행 배치파일
REM Windows 작업 스케줄러에 등록하여 사용

cd /d "%~dp0.."
python scripts\scheduled_auto_update.py

pause
