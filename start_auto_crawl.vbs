Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "cmd /c cd /d C:\Users\MSI\Desktop\Coupong && C:\Users\MSI\AppData\Local\Programs\Python\Python310\python.exe scripts\auto_crawl.py", 0, False
