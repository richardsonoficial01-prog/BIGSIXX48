@echo off
setlocal
cd /d "%~dp0"

set "CLIPPER_PYTHON=py -3"
where py >nul 2>nul
if errorlevel 1 set "CLIPPER_PYTHON=python"
%CLIPPER_PYTHON% -c "import sys; assert sys.version_info >= (3, 10), 'Use Python 3.10 ou superior.'"
if errorlevel 1 (
  echo Instale Python 3.10 ou superior com a opcao de adicionar ao PATH.
  pause
  exit /b 1
)
where ffmpeg >nul 2>nul
if errorlevel 1 goto missing_ffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto missing_ffmpeg

if not exist ".venv\Scripts\python.exe" (
  %CLIPPER_PYTHON% -m venv .venv
  if errorlevel 1 goto failed
)
fc /b requirements.txt .venv\clipper-requirements.txt >nul 2>nul
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
  if errorlevel 1 goto failed
  copy /y requirements.txt .venv\clipper-requirements.txt >nul
)
echo Abra http://127.0.0.1:8000 no navegador.
echo Mantenha esta janela aberta enquanto usar o app.
.venv\Scripts\python.exe server.py
if errorlevel 1 goto failed
exit /b 0

:missing_ffmpeg
echo Instale FFmpeg com ffprobe e adicione os comandos ao PATH.
echo Alternativa: execute docker compose up --build nesta pasta.
pause
exit /b 1

:failed
echo Nao foi possivel iniciar. Confira a mensagem acima.
pause
exit /b 1
