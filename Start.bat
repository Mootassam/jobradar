@echo off
title JobRadar
cd /d "%~dp0"
python -c "import flask, waitress, requests, bs4, lxml, phonenumbers, openpyxl, dns" 2>nul || (
  echo Installing JobRadar requirements...
  python -m pip install -r requirements.txt
)
set JOBRADAR_OPEN_BROWSER=1
python server.py
pause
