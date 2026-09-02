param(
    [string]$ToolchainBin = 'E:\Xilinx\SDK\2019.1\gnu\aarch32\nt\gcc-arm-linux-gnueabi\bin',
    [switch]$Clean,
    [switch]$EnableFpga
)

$ErrorActionPreference = 'Stop'
if ($EnableFpga) {
    throw 'FPGA builds were retired from the SDR Agent project on 2026-09-02. Build the Linux/IIO-only sdrd instead.'
}
$SdrdRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$BuildRoot = Join-Path $SdrdRoot 'build-armhf-dynamic'
$Output = Join-Path $BuildRoot 'sdrd'
$Compiler = Join-Path $ToolchainBin 'arm-linux-gnueabihf-gcc.exe'
$Strip = Join-Path $ToolchainBin 'arm-linux-gnueabihf-strip.exe'
$Readelf = Join-Path $ToolchainBin 'arm-linux-gnueabihf-readelf.exe'

if ($Clean) {
    $ExpectedBuildRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $SdrdRoot 'build-armhf-dynamic'))
    if (Test-Path -LiteralPath $BuildRoot) {
        $ResolvedBuildRoot = (Resolve-Path -LiteralPath $BuildRoot).Path
        if ($ResolvedBuildRoot -ne $ExpectedBuildRoot) {
            throw "Refusing to clean unexpected build path: $ResolvedBuildRoot"
        }
        Remove-Item -LiteralPath $ResolvedBuildRoot -Recurse -Force
    }
    Write-Output 'armhf_build_cleanup=verified'
    return
}

foreach ($Tool in @($Compiler, $Strip, $Readelf)) {
    if (-not (Test-Path -LiteralPath $Tool -PathType Leaf)) {
        throw "Missing ARM toolchain executable: $Tool"
    }
}

New-Item -ItemType Directory -Force -Path $BuildRoot | Out-Null
$Arguments = @(
    "-I$(Join-Path $SdrdRoot 'include')",
    '-std=c11', '-O2', '-Wall', '-Wextra', '-Wpedantic', '-Werror',
    '-o', $Output,
    (Join-Path $SdrdRoot 'src\main.c'),
    (Join-Path $SdrdRoot 'src\sdrd.c'),
    (Join-Path $SdrdRoot 'src\sdrd_iio.c')
)
$Arguments += @('-ldl', '-pthread')

& $Compiler @Arguments
if ($LASTEXITCODE -ne 0) { throw "ARM compilation failed: $LASTEXITCODE" }
& $Strip $Output
if ($LASTEXITCODE -ne 0) { throw "ARM strip failed: $LASTEXITCODE" }

$VersionInfo = (& $Readelf --version-info $Output) -join "`n"
$Versions = [regex]::Matches($VersionInfo, 'GLIBC_[0-9.]+') |
    ForEach-Object { $_.Value } | Sort-Object -Unique
$Hash = (Get-FileHash -LiteralPath $Output -Algorithm SHA256).Hash.ToLowerInvariant()

Write-Output "artifact=$Output"
Write-Output "sha256=$Hash"
Write-Output "required_glibc=$($Versions -join ',')"
Write-Output 'fpga_compiled=false'
