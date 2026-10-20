@echo off
TITLE Ngrok Tunnel - Porta 3000
SETLOCAL

echo =======================================================
echo   Iniciando Tunel de Ngrok (Puerto 3000)
echo =======================================================

:: Verificar si ngrok esta instalado
where ngrok >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] No encuentro 'ngrok' instalado en tu sistema.
    echo Por favor, descargalo de https://ngrok.com/download e instalalo.
    pause
    exit /b
)

echo [INFO] Levantando tunel...
echo -------------------------------------------------------
echo COPIA EL LINK QUE APARECE LUEGO DE 'Forwarding' (ej: https://xxxx.ngrok-free.app)
echo Y RECORDA AGREGARLE '/webhook' AL FINAL EN EL PANEL DE META.
echo -------------------------------------------------------

ngrok http 3000

pause
