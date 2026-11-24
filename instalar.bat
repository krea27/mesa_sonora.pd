@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ========================================================
echo   Instalador de Mesa Sonora (Sonomontaje + PlugData)
echo ========================================================
echo.

set "PY_CMD="
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY_CMD=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY_CMD=py -3"
    )
)

if "%PY_CMD%"=="" (
    echo [ERROR] No se encontro Python instalado en el sistema.
    echo Descargalo desde https://www.python.org/downloads/
    echo (Recorda tildar "Add Python to PATH" durante la instalacion).
    echo.
    pause
    exit /b 1
)

echo [1/3] Creando entorno virtual (.venv)...
if not exist ".venv\Scripts\python.exe" (
    %PY_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
) else (
    echo       Entorno virtual existente detectado.
)

echo.
echo [2/3] Actualizando pip e instalando dependencias de Python...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [ERROR] Fallo la instalacion de dependencias. Verifica tu conexion a internet.
    pause
    exit /b 1
)

echo.
echo [3/3] Verificando PlugData / Pure Data...
set "PD_FOUND=0"
if exist "C:\Program Files\plugdata\plugdata.exe" set "PD_FOUND=1"
if exist "%LOCALAPPDATA%\Programs\plugdata\plugdata.exe" set "PD_FOUND=1"
if exist "C:\Program Files\Pd\bin\pd.exe" set "PD_FOUND=1"
if exist "C:\Program Files (x86)\Pd\bin\pd.exe" set "PD_FOUND=1"

if "%PD_FOUND%"=="1" (
    echo       PlugData / Pure Data detectado correctamente.
) else (
    echo [AVISO] No se detecto PlugData ni Pure Data en las rutas estandar.
    echo         Instalalo desde https://plugdata.org para escuchar el audio.
)

echo.
echo ========================================================
echo   Instalacion completada.
echo   Ejecuta "iniciar.bat" para abrir Mesa Sonora.
echo ========================================================
pause
