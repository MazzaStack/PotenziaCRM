@echo off
TITLE CRM - Publicador Redes Sociales
echo ==========================================
echo   INICIANDO PUBLICADOR DE HISTORIAS
echo ==========================================
echo.

:: Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no está instalado o no está en el PATH.
    pause
    exit /b
)

echo [1/1] Iniciando Social Publisher...
echo El robot procesará las placas programadas entre las 08:00 y las 23:00.
echo.

python lib/social_publisher.py

pause
