@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "RC=0"

rem ============================================================
rem PLUZ-AllStar.bat -- the whole PLUZ5 pipeline in one shot:
rem   sync -> check -> fetch -> build -> validate -> commit/push
rem
rem Stops at the first failing step and says which one. The window
rem stays open at the end when you double-click this file.
rem Tool locations, repo name and token come from .env (see .env.example).
rem
rem DEBUG MODE (off by default). Turn it on any of these ways:
rem   - put  PLUZ_DEBUG=1  in .env            (stays on until you set 0)
rem   - run  PLUZ-AllStar.bat debug           (this run only)
rem   - run  PLUZ-AllStar.bat nodebug         (forces it off for this run)
rem When on: prints a diagnostic report (token hidden), turns on git's own
rem tracing, always pauses at the end, and saves the full output to
rem logs\allstar_debug_<time>.log -- send me that file if something breaks.
rem
rem Stuck with saved or wrong GitHub logins? Run PLUZ-GHclean.bat.
rem ============================================================

call "%~dp0pluz-env.bat"
if not defined GH_BRANCH set "GH_BRANCH=main"
if not exist "%~dp0logs" mkdir "%~dp0logs"

rem ---- never let git open a sign-in window or wait for typing ----
rem (it fails with a clear message instead). Set PLUZ_ALLOW_PROMPT=1 to allow it.
set "NOHELP="
if not "%PLUZ_ALLOW_PROMPT%"=="1" (
    set "GIT_TERMINAL_PROMPT=0"
    set "GCM_INTERACTIVE=never"
    set "NOHELP=-c credential.helper="
)

if not defined PLUZ_DEBUG set "PLUZ_DEBUG=0"
for %%A in (%*) do (
    if /i "%%A"=="debug" set "PLUZ_DEBUG=1"
    if /i "%%A"=="--debug" set "PLUZ_DEBUG=1"
    if /i "%%A"=="nodebug" set "PLUZ_DEBUG=0"
    if /i "%%A"=="--nodebug" set "PLUZ_DEBUG=0"
    if /i "%%A"=="--inner" set "PLUZ_INNER=1"
)
set "COMMIT_MSG=auto: PLUZ-AllStar pipeline run"

"%PY%" --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Python not found. Set PLUZ_PY_DIR or PLUZ_PYTHON in .env.
    set "RC=1"
    goto :end
)
"%GIT%" --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL] Git not found. Set PLUZ_GIT_DIR or PLUZ_GIT in .env.
    set "RC=1"
    goto :end
)

rem Debug on and not yet logging: run this same script again with its output
rem copied to a log file, then come back here to finish.
if "%PLUZ_DEBUG%"=="1" if not defined PLUZ_INNER (
    "%PY%" "core\pluz_tee.py" cmd /c call "%~f0" --inner
    if errorlevel 1 set "RC=1"
    goto :end
)

echo Python: %PY%
echo Git:    %GIT%
if "%PLUZ_DEBUG%"=="1" (
    echo.
    echo [DEBUG] ON  -  turn off with: PLUZ-AllStar.bat nodebug
    "%PY%" "core\pluz_debug.py"
    set "GIT_TRACE=1"
    set "GIT_CURL_VERBOSE=1"
    set "GIT_TRACE_REDACT=1"
)

rem Build the sign-in header from GH_USER + GH_TOKEN (written to a temp file
rem and read back, which avoids cmd's nested-quote problems).
set "GHAUTH="
"%PY%" "core\pluz_ghauth.py" > "%TEMP%\pluz_auth.tmp" 2>nul
set /p GHAUTH=<"%TEMP%\pluz_auth.tmp"
del "%TEMP%\pluz_auth.tmp" >nul 2>&1
if defined GHAUTH (
    echo Signing in to GitHub with GH_TOKEN from .env
) else (
    echo No GH_TOKEN could be read from .env
)
echo.
echo ==================== [0/5] sync with GitHub ====================
"%GIT%" rev-parse --is-inside-work-tree >nul 2>&1
if errorlevel 1 (
    if not defined GH_USER (
        echo [FAIL] This folder is not a git repo and GH_USER / GH_REPO are not set in .env.
        set "RC=1"
        goto :end
    )
    echo This folder is not a git repo yet. Connecting it to https://github.com/%GH_USER%/%GH_REPO%
    "%GIT%" init -b %GH_BRANCH%
    "%GIT%" remote add origin https://github.com/%GH_USER%/%GH_REPO%.git
    "%GIT%" %NOHELP% -c "http.extraheader=%GHAUTH%" fetch origin
    if errorlevel 1 echo [WARN] Could not read the GitHub repo yet - will try to push anyway. Check GH_USER / GH_REPO / GH_TOKEN in .env.
    "%GIT%" reset origin/%GH_BRANCH% >nul 2>&1
)
"%GIT%" remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo [FAIL] No remote named origin. Run: git remote add origin https://github.com/%GH_USER%/%GH_REPO%.git
    set "RC=1"
    goto :end
)

"%GIT%" %NOHELP% -c "http.extraheader=%GHAUTH%" pull --rebase --autostash origin %GH_BRANCH%
if errorlevel 1 echo [WARN] Could not pull the latest from GitHub - continuing. If the push fails at the end, run this again with: debug

call :step "[1/5] pluz-check" pluz_check.py || goto :end
call :step "[2/5] pluz-fetch" pluz_fetch.py --apply || goto :end
call :step "[3/5] pluz-update" pluz_update.py || goto :end
call :step "[4/5] pluz-validate" pluz_validate.py || goto :end

echo.
echo ==================== [5/5] git add / commit / push ====================
if not defined GHAUTH if not "%PLUZ_ALLOW_PROMPT%"=="1" (
    echo [FAIL] GH_TOKEN is missing or was not read from .env, so the push cannot sign in.
    echo        Put GH_USER=... and GH_TOKEN=... in .env ^(no quotes, no spaces^), or run: PLUZ-AllStar.bat debug
    set "RC=1"
    goto :end
)
"%GIT%" add -A
if errorlevel 1 (
    echo [FAIL] git add failed.
    set "RC=1"
    goto :end
)
set "GITCFG="
"%GIT%" config user.name >nul 2>&1
if errorlevel 1 set "GITCFG=-c user.name=%GH_USER% -c user.email=%GH_USER%@users.noreply.github.com"
"%GIT%" diff --cached --quiet
if errorlevel 1 (
    "%GIT%" %GITCFG% commit -m "%COMMIT_MSG%"
    if errorlevel 1 (
        echo [FAIL] git commit failed - see the text above.
        set "RC=1"
        goto :end
    )
) else (
    echo Nothing new to commit - pushing any earlier commits that are still waiting.
)
"%GIT%" %NOHELP% -c "http.extraheader=%GHAUTH%" push -u origin %GH_BRANCH%
if errorlevel 1 (
    echo [FAIL] git push failed - committed locally but not pushed.
    echo        Check GH_TOKEN in .env: it needs this repo with Contents AND Workflows set to Read and write.
    echo        Run PLUZ-AllStar.bat debug and send me the log in the logs folder, or run PLUZ-GHclean.bat.
    set "RC=1"
    goto :end
)
echo Pushed.
if "%PLUZ_DEBUG%"=="1" "%GIT%" log --oneline -3
goto :end

:step
echo.
echo ==================== %~1 ====================
"%PY%" "core\%~2" %~3
if errorlevel 1 (
    echo.
    echo [FAIL] %~1 failed - stopping. The newest file in the logs folder has the details.
    exit /b 1
)
exit /b 0

:end
echo.
if "%RC%"=="0" (echo ==================== AllStar finished ====================) else (echo ==================== AllStar STOPPED - see the FAIL line above ====================)
if defined PLUZ_INNER exit /b %RC%
if "%PLUZ_DEBUG%"=="1" (
    pause
    exit /b %RC%
)
echo "%cmdcmdline%" | find /i "%~nx0" >nul && pause
exit /b %RC%
