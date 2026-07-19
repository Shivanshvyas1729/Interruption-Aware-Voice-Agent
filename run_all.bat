@echo off
echo ===================================================
echo   Spawning Pivot Voice Agent Services
echo ===================================================

:: Path to the Miniconda activation script on your system
set CONDA_ACTIVATE=C:\Users\DELL\miniconda3\Scripts\activate.bat

:: Launch API Gateway
echo Starting API Gateway on Port 8003...
start "API Gateway (Port 8003)" cmd /k "call "%CONDA_ACTIVATE%" voice-agent && python -m services.edge_auth.api_gateway"

:: Launch Orchestrator
echo Starting Orchestrator on Port 8000...
start "Orchestrator (Port 8000)" cmd /k "call "%CONDA_ACTIVATE%" voice-agent && python -m services.orchestrator.main 8000"

:: Launch Media Gateway
echo Starting Media Gateway on Port 8001...
start "Media Gateway (Port 8001)" cmd /k "call "%CONDA_ACTIVATE%" voice-agent && python -m services.media_gateway.main 8001"

:: Launch Web Client server
echo Starting Web Server on Port 8080...
start "Web Server (Port 8080)" cmd /k "python -m http.server 8080 --directory client/phase1_minimal_harness"

echo ===================================================
echo   All services launched in separate windows!
echo ===================================================
