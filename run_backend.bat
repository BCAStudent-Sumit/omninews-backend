@echo off
title OmniNews Django Server + Auto-News Pipeline (0.0.0.0:8000)
cd /d "D:\My project\omninews_backend"
echo ========================================================
echo  Starting OmniNews Django Server on 0.0.0.0:8000...
echo  - Automated News Ingestion: ACTIVE (Auto-fetches every 10 min)
echo  - Swagger API Docs: http://127.0.0.1:8000/api/docs/
echo ========================================================
python manage.py runserver 0.0.0.0:8000
pause
