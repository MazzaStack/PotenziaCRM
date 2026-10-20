@echo off
TITLE CRM Inmobiliario - Servidor Principal
set PYTHONUTF8=1
echo ==========================================
echo   LANZANDO CRM INMOBILIARIO (VENV)
echo ==========================================
echo.

:: Verificar si Python está instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no está instalado o no está en el PATH.
    pause
    exit /b
)

:: Crear entorno virtual si no existe
if not exist venv (
    echo [1/3] Creando entorno virtual aislado venv...
    python -m venv venv
)

echo [2/3] Activando entorno y verificando dependencias...
call venv\Scripts\activate
python -m pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

echo [3/3] Iniciando Meta AI Chatbot (ClaudIA)...
start "Meta AI Chatbot" cmd /c "cd plugins\meta_ai\chatbot && run_bot.bat"

echo [4/4] Iniciando servidor Flask...
echo El panel estará disponible en: http://localhost:5000
echo.

:: Abrir el navegador automáticamente
start http://localhost:5000

:: Ejecutar la aplicación
python app.py

pause
