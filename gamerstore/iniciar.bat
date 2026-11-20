@echo off
cd /d "%~dp0"
start "" http://127.0.0.1:6200
python -I server.py
