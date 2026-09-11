@echo off
cd /d "%~dp0"
echo 売上ダッシュボードのサーバーを起動しています...
start "売上ダッシュボード サーバー" "C:\Users\9520049\AppData\Local\Programs\Python\Python313\python.exe" "%~dp0dashboard_server.py"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/"
