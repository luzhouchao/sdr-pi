$workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$xsetupBat = "E:\Xilinx\.xinstall\Vivado_2019.1\bin\xsetup.bat"
$sourceConfig = Join-Path $workspace "vivado2019_zynq7000_install_config.txt"
$asciiConfig = "E:\vivado\p201pro_zynq7000_add_config.txt"
$asciiLog = "E:\vivado\p201pro_zynq7000_add.log"
$asciiCmd = "E:\vivado\p201pro_zynq7000_add.cmd"
$payloadRoot = "E:\vivado\Vivado_SDK_2019.1_0524_1430\Xilinx_Vivado_SDK_2019.1_0524_1430"

if (-not (Test-Path -LiteralPath $xsetupBat)) {
    throw "Existing Vivado 2019.1 add-tools xsetup.bat was not found: $xsetupBat"
}
if (-not (Test-Path -LiteralPath $sourceConfig)) {
    throw "Zynq-7000 add config was not found: $sourceConfig"
}
if (-not (Test-Path -LiteralPath (Join-Path $payloadRoot "payload"))) {
    throw "Offline payload directory was not found: $payloadRoot\payload"
}

Copy-Item -LiteralPath $sourceConfig -Destination $asciiConfig -Force

$cmdText = @"
@echo off
cd /d E:\Xilinx\.xinstall\Vivado_2019.1
echo Running Vivado 2019.1 Add Design Tools or Devices batch flow...
echo Existing xsetup: $xsetupBat
echo Expected payload root: $payloadRoot
echo Config: $asciiConfig
echo Log: $asciiLog
bin\xsetup.bat -a XilinxEULA,3rdPartyEULA -b Add -c "$asciiConfig" > "$asciiLog" 2>&1
echo.
echo Done. Exit code: %ERRORLEVEL%
echo Log tail:
type "$asciiLog"
pause
"@

Set-Content -LiteralPath $asciiCmd -Value $cmdText -Encoding ASCII

Write-Host "Launching Vivado 2019.1 Add Design Tools or Devices batch flow as administrator."
Write-Host "Command file:"
Write-Host "  $asciiCmd"
Write-Host "Config:"
Write-Host "  $asciiConfig"
Write-Host "Log:"
Write-Host "  $asciiLog"

Start-Process -FilePath "cmd.exe" -ArgumentList "/k `"$asciiCmd`"" -WorkingDirectory "E:\vivado" -Verb RunAs
