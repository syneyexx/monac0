@echo off
cd /d %~dp0
if exist .venv\Scripts\python.exe (.venv\Scripts\python.exe run_m0n4c0.py --gui) else py -3.11 run_m0n4c0.py --gui
pause
