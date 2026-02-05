$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument '/c cd /d C:\Users\MSI\Desktop\Coupong && C:\Users\MSI\AppData\Local\Programs\Python\Python310\Scripts\streamlit.exe run dashboard.py --server.address 0.0.0.0 --server.port 8501 --server.headless true' `
    -WorkingDirectory "C:\Users\MSI\Desktop\Coupong"

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask `
    -TaskName "CoupongDashboard" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Force

Write-Host "[OK] CoupongDashboard 자동 시작 등록 완료!" -ForegroundColor Green
Write-Host "Tailscale IP: $(& 'C:\Program Files\Tailscale\tailscale.exe' ip -4 2>$null)" -ForegroundColor Cyan
