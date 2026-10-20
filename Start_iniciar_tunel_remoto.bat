@echo off
ngrok config add-authtoken 3AjGPvLCSRzwegeJRZ6kCNO58db_6ib49Q6VTB5HLfX198LNh
title Tunel Remoto - CRM Inmobiliario
echo ==========================================
echo Iniciando Ngrok para acceso Multi-plataforma
echo ==========================================
echo.
echo REQUISITO: Debes tener instalado Ngrok (ngrok.com) 
echo y haber configurado tu authtoken: 'correr ngrok con el commando para instalar el token'
echo.
echo Abriendo puerto 5000...
ngrok http 5000
pause
