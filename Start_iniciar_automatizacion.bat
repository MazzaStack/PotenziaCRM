@echo off
echo ==================================================
echo   CRM - AI Automation
echo ==================================================
echo.
echo [1/2] Iniciando Generador de Mensajes (Worker)...
start "AI Message Worker" cmd /c "set PYTHONPATH=. && python lib/automation_worker.py && pause"

echo [2/2] Iniciando WhatsApp Bridge (Navegador)...
echo.
echo NOTA: Si es la primera vez, el navegador se abrira y tendras que
echo escanear el codigo QR de tu WhatsApp.
echo.
set PYTHONPATH=.
python lib/whatsapp_sender.py

pause
