@echo off
TITLE CRM Captador - SUPER TUNEL MOVIL 📱
COLOR 0B

echo ==================================================
echo         CRM CAPTADOR - ACCESO REMOTO MOVIL
echo ==================================================
echo.
echo [1/3] Verificando entorno...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] No se encontro Python. Por favor instala Python.
    pause
    exit /b
)

echo [2/3] Lanzando Servidor del CRM en segundo plano...
:: Lanzamos el servidor Flask en una ventana separada
start "CRM Server" /min cmd /c "python app.py"

echo.
echo [3/3] Iniciando Tunel de Internet (Ngrok)...
echo.
echo --------------------------------------------------
echo INSTRUCCIONES PARA TU CELULAR:
echo 1. Espera a que Ngrok muestre la direccion 'Forwarding'.
echo 2. Sera algo como: https://XXXX-XXXX.ngrok-free.app
echo 3. Copia esa direccion y abrila en el navegador de tu movil.
echo 4. Si aparece una pantalla de Ngrok, dale a 'Visit Site'.
echo --------------------------------------------------
echo.
echo REQUISITO: Debes tener Ngrok instalado y tu authtoken configurado.
echo (Comando: ngrok config add-authtoken 3AjGPvLCSRzwegeJRZ6kCNO58db_6ib49Q6VTB5HLfX198LNh)
echo.

:: Ejecutamos Ngrok en el puerto 5000 (donde vive Flask)
ngrok http 5000

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] No se pudo iniciar Ngrok. 
    echo Asegurate de tenerlo descargado desde ngrok.com y estar registrado.
    echo.
    pause
)
