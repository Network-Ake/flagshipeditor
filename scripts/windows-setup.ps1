#Requires -Version 5.1
# Compatibility entry point. The complete installer lives beside this file.
& (Join-Path $PSScriptRoot "Install-FlagshipEditor.ps1") @args
exit $LASTEXITCODE
