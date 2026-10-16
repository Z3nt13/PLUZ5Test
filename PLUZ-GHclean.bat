@echo off
setlocal EnableExtensions
cd /d "%~dp0"
call "%~dp0pluz-env.bat"
set "RC=0"

rem ============================================================
rem PLUZ-GHclean.bat -- clean slate before uploading to GitHub.
rem   PLUZ-GHclean.bat                 menu
rem   PLUZ-GHclean.bat all             preview everything (changes nothing)
rem   PLUZ-GHclean.bat local|creds|repo|all  --apply
rem Everything here is a preview until you add --apply or pick a menu number.
rem ============================================================

if not "%~1"=="" (
    "%PY%" "core\pluz_ghclean.py" %*
    set "RC=%ERRORLEVEL%"
    goto :end
)

:menu
echo.
echo ============ PLUZ GHclean ============
echo   1  Preview everything (changes nothing)
echo   2  Clean local junk (old logs, caches, temp files)
echo   3  Forget saved GitHub logins (stops the credential pop-up)
echo   4  Reset repo history and upload clean (asks you to type CLEAN)
echo   5  Do 2, 3 and 4
echo   0  Quit
echo.
set "CH="
set /p "CH=Choose: "
if "%CH%"=="1" "%PY%" "core\pluz_ghclean.py" all
if "%CH%"=="2" "%PY%" "core\pluz_ghclean.py" local --apply
if "%CH%"=="3" "%PY%" "core\pluz_ghclean.py" creds --apply
if "%CH%"=="4" "%PY%" "core\pluz_ghclean.py" repo --apply
if "%CH%"=="5" "%PY%" "core\pluz_ghclean.py" all --apply
if "%CH%"=="0" goto :end
goto :menu

:end
echo "%cmdcmdline%" | find /i "%~nx0" >nul && pause
exit /b %RC%
