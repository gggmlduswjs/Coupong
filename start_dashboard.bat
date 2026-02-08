@echo off
chcp 65001 >nul
title Coupong Dashboard
cd /d "C:\Users\MSI\Desktop\Coupong"
echo [%date% %time%] 대시보드 시작 중...
"C:\Users\MSI\AppData\Local\Programs\Python\Python310\Scripts\streamlit.exe" run dashboard.py
pause
