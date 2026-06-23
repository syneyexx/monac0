@echo off
cd /d %~dp0
py -3.11 run_m0n4c0.py --gui --safe-mode
pause
