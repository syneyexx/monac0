@echo off
cd /d %~dp0
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe run_m0n4c0.py --worker --agents 3) else py -3.11 run_m0n4c0.py --worker --agents 3
pause
