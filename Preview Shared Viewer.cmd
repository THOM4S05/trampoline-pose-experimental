@echo off
title Flightroom Shared Viewer - Local Preview
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-shared-viewer.ps1"
if errorlevel 1 pause
