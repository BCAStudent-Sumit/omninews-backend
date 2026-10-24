@echo off
echo ========================================================
echo  Starting OmniNews Background Ingestion (Celery)
echo  1. Celery Worker (Pool: solo)
echo  2. Celery Beat Scheduler (Every 10 min)
echo ========================================================

REM Launch Worker in a separate window
start "OmniNews Celery Worker" cmd /k "cd /d "D:\My project\omninews_backend" && celery -A omninews_backend worker -l info -P solo"

REM Launch Beat in a separate window
start "OmniNews Celery Beat" cmd /k "cd /d "D:\My project\omninews_backend" && celery -A omninews_backend beat -l info"

echo.
echo Both Worker and Beat have been launched in separate windows!
echo You can keep them minimized in the background.
echo.
pause
