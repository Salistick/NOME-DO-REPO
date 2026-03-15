@echo off
setlocal

set PYTHON_EXE=

where python >nul 2>nul
if %errorlevel%==0 set PYTHON_EXE=python

if not defined PYTHON_EXE (
    where py >nul 2>nul
    if %errorlevel%==0 set PYTHON_EXE=py -3
)

if not defined PYTHON_EXE (
    echo Python nao encontrado no PATH.
    exit /b 1
)

echo Instalando dependencias...
%PYTHON_EXE% -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo Limpando build anterior...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Gerando executavel...
%PYTHON_EXE% -m PyInstaller --clean bot_live.spec
if errorlevel 1 exit /b 1

echo.
echo Build concluido.
echo Coloque o arquivo .env dentro de dist\
echo Execute dist\TTSLive.exe

endlocal
