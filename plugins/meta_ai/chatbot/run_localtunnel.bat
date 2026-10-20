@echo off
TITLE Localtunnel - Puerto 3000
echo =======================================================
echo   Iniciando Tunel de Localtunnel (Puerto 3000)
echo =======================================================
echo [INFO] Levantando tunel...
echo -------------------------------------------------------
echo COPIA EL LINK QUE APARECE LUEGO DE 'your url is:'
echo Y RECORDA AGREGARLE '/webhook' AL FINAL EN EL PANEL DE META.
echo -------------------------------------------------------
npx localtunnel --port 3000
pause
