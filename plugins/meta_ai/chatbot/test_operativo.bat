@echo off
title ClaudIA Pro - Simulador de Operatividad
set /p lead_name="Ingrese el nombre del Lead para el test (o enter para 'Carlos'): "
if "%lead_name%"=="" set lead_name=Carlos

echo Instando simulacion para: %lead_name%...
node test_claudia.js "%lead_name%"
pause
