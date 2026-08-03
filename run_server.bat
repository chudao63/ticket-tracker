@echo off
REM Chay Ticket Tracker nen, tu khoi dong lai neu crash. Duoc goi boi Scheduled Task
REM "TicketTrackerServer" (chay bang SYSTEM, trigger At startup) - xem README_DEPLOY.txt.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
REM Giu nguyen mat khau admin cu (truoc day hardcode trong code, gio phai dat qua env var).
if not defined TICKET_ADMIN_KEY set TICKET_ADMIN_KEY=Adhnt4125@
:loop
"C:\Python314\python.exe" app.py >> server.log 2>&1
echo [%date% %time%] app.py thoat, khoi dong lai sau 5 giay... >> server.log
timeout /t 5 /nobreak >nul
goto loop
