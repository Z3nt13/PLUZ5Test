@echo off
rem pluz-env.bat -- shared by every PLUZ launcher. Reads .env and sets PY and GIT.
rem Only .env is ever edited; nothing personal lives in this file.
rem   PLUZ_PYTHON   full path to python.exe (optional, wins if set)
rem   PLUZ_PY_DIR   folder holding a portable Python/WinPython (searched for python.exe)
rem   PLUZ_GIT      full path to git.exe (optional, wins if set)
rem   PLUZ_GIT_DIR  folder of a portable Git (cmd\git.exe or bin\git.exe)
rem Anything unset falls back to python / git on PATH.
set "PY=" & set "GIT="
if exist "%~dp0.env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%~dp0.env") do set "%%A=%%~B"
)
if defined PLUZ_PYTHON if exist "%PLUZ_PYTHON%" set "PY=%PLUZ_PYTHON%"
if not defined PY if defined PLUZ_PY_DIR if exist "%PLUZ_PY_DIR%" (
    for /f "delims=" %%P in ('dir /s /b "%PLUZ_PY_DIR%\python.exe" 2^>nul') do if not defined PY set "PY=%%P"
)
if not defined PY set "PY=python"
if defined PLUZ_GIT if exist "%PLUZ_GIT%" set "GIT=%PLUZ_GIT%"
if not defined GIT if defined PLUZ_GIT_DIR (
    if exist "%PLUZ_GIT_DIR%\cmd\git.exe" set "GIT=%PLUZ_GIT_DIR%\cmd\git.exe"
    if not defined GIT if exist "%PLUZ_GIT_DIR%\bin\git.exe" set "GIT=%PLUZ_GIT_DIR%\bin\git.exe"
    if exist "%PLUZ_GIT_DIR%\bin" set "PATH=%PLUZ_GIT_DIR%\bin;%PLUZ_GIT_DIR%\cmd;%PATH%"
)
if not defined GIT set "GIT=git"
set "PLUZ_GIT=%GIT%"
set "PLUZ_PYTHON=%PY%"
