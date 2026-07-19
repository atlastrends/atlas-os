@echo off
REM ============================================================
REM  ATLAS OS - INICIAR (um clique)
REM  De dois cliques neste arquivo para abrir o ATLAS.
REM  Ele instala o que faltar, cria o link publico e abre o
REM  painel no navegador automaticamente.
REM ============================================================
cd /d "%~dp0"
title ATLAS OS
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0atlas.ps1"
echo.
echo O ATLAS foi encerrado. Voce pode fechar esta janela.
pause
