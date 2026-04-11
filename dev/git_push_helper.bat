@echo off
echo Cleaning git locks...
if exist ".git\index.lock" del /f ".git\index.lock"
if exist ".git\HEAD.lock" del /f ".git\HEAD.lock"
if exist ".git\objects\maintenance.lock" del /f ".git\objects\maintenance.lock"

echo Staging...
git add installer/installer_gui.py .gitignore

echo Committing...
git commit -m "feat: add remote ComfyUI connect on Welcome step + rebuild.bat for SFW/NSFW"

echo Pushing...
git push origin main

echo Done!
pause
