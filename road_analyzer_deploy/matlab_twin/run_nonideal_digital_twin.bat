@echo off
REM ============================================================
REM Double-click this file to generate the NON-IDEAL (defects) 3D
REM RoadRunner simulation from your latest analysis.
REM
REM It must live in the same matlab_twin\ folder as
REM auto_import_roadrunner.m -- it finds that folder automatically
REM from its own location, so this works no matter where you cloned
REM the repo.
REM ============================================================
setlocal

if "%MATLAB_EXE%"=="" (
    set "MATLAB_EXE=C:\Program Files\MATLAB\R2026a\bin\matlab.exe"
)

if not exist "%MATLAB_EXE%" (
    echo Could not find MATLAB at:
    echo   %MATLAB_EXE%
    echo Either install MATLAB there, or set the MATLAB_EXE environment
    echo variable to your real matlab.exe path, then run this file again.
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"

echo Launching MATLAB and RoadRunner for the NON-IDEAL (defect) road...
echo (this window will stay open while the simulation runs -- close it when done)
echo.

"%MATLAB_EXE%" -sd "%SCRIPT_DIR%" -r "auto_import_roadrunner('nonideal')"

endlocal
