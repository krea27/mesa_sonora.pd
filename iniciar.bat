@echo off
cd /d "%~dp0"
echo ========================================================
echo Iniciando Mesa Sonora - Sonomontaje + PlugData DSP...
echo (PlugData se abrira automaticamente con mesa_sonora.pd)
echo ========================================================

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" mesa_sonora.py %*
) else (
    where python >nul 2>nul
    if %errorlevel%==0 (
        python mesa_sonora.py %*
    ) else (
        py -3 mesa_sonora.py %*
    )
)
pause
