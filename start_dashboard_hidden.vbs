Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d C:\Users\MSI\Desktop\Coupong && C:\Users\MSI\AppData\Local\Programs\Python\Python310\Scripts\streamlit.exe run dashboard.py --server.address 0.0.0.0 --server.port 8503 --server.headless true", 0, False
