@echo off
REM ============================================================
REM 2D digital twin in MATLAB only (no RoadRunner needed)
REM Keep this file in the same folder as the .m scripts and the
REM .xodr / _roadrunner_capacity.json files from the dashboard bundle.
REM A log of every run is written to twin_log.txt in this folder.
REM ============================================================
setlocal EnableDelayedExpansion

REM ---- find matlab.exe: MATLAB_EXE env var, then PATH, then newest install
if defined MATLAB_EXE if exist "%MATLAB_EXE%" goto :found
for /f "delims=" %%M in ('where matlab 2^>nul') do (set "MATLAB_EXE=%%M" & goto :found)
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\MATLAB\R20*" 2^>nul') do (
    if exist "%ProgramFiles%\MATLAB\%%D\bin\matlab.exe" (
        set "MATLAB_EXE=%ProgramFiles%\MATLAB\%%D\bin\matlab.exe" & goto :found
    )
)
echo Could not find MATLAB.
echo Set MATLAB_EXE to your matlab.exe, for example:
echo   setx MATLAB_EXE "C:\Program Files\MATLAB\R2025b\bin\matlab.exe"
echo then open a new window and run this file again.
pause
exit /b 1

:found
REM %~dp0 ends with "\" - inside quotes that becomes \" and breaks the
REM argument, so strip it.
set "HERE=%~dp0"
set "HERE=%HERE:~0,-1%"

echo Using MATLAB: %MATLAB_EXE%
echo Folder:       %HERE%
echo.
echo Starting MATLAB (2D twin). The first start can take 1-2 minutes.
echo This window stays open until MATLAB is closed.
echo.

"%MATLAB_EXE%" -wait -sd "%HERE%" -r "run_twin_safely('2d')"

echo.
echo MATLAB closed. If nothing appeared, open twin_log.txt in this folder.
pause
endlocal
