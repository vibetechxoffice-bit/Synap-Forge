@echo off
if not exist "launcher.py" (
    echo ERROR: launcher.py not found!
    pause
    goto end
)

python launcher.py || (
    echo Failed to run python script.
    pause
)
:end
pause
