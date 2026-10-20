@echo off
TITLE Meta AI Chatbot Connector - German Mazzaferro
SETLOCAL

echo =======================================================
echo   Iniciando Meta AI Chatbot Connector
echo =======================================================

:: Verificar si existe el archivo .env
if not exist .env (
    echo [ERROR] No se encuentra el archivo .env
    echo Por favor, renombra .env.example a .env y configura tu GEMINI_API_KEY.
    pause
    exit /b
)

:: Verificar si node_modules existe, si no, instalar dependencias
if not exist node_modules (
    echo [INFO] Instalando dependencias necesarias...
    call npm install
)

echo [INFO] Arrancando el servidor...
echo [INFO] Recuerda tener tu celular a mano para escanear el QR si es la primera vez.
echo -------------------------------------------------------

:: Ejecutar la aplicacion
node index.js

if %ERRORLEVEL% neq 0 (
    echo -------------------------------------------------------
    echo [ERROR] Hubo un problema al ejecutar el bot.
    pause
)

pause
