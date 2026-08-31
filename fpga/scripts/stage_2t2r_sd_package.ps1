$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$packageRoot = Join-Path $repoRoot "deliverables\p201pro_2t2r_sd_project"
$asciiWorkRoot = "E:\vivado\p201pro_2t2r_sd_project"

$generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"

New-Item -ItemType Directory -Force -Path $packageRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "hdl") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "scripts") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "reports") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "sd_overlay") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $packageRoot "vivado_project") | Out-Null

$hdlSource = Join-Path $repoRoot "hdl_out\builtin_power\p201pro_builtin_power_hdl_model"
Copy-Item -LiteralPath (Join-Path $hdlSource "p201pro_builtin_power_hdl_model.v") -Destination (Join-Path $packageRoot "hdl") -Force
Copy-Item -LiteralPath (Join-Path $hdlSource "peak_power.v") -Destination (Join-Path $packageRoot "hdl") -Force

Copy-Item -LiteralPath (Join-Path $repoRoot "scripts\vivado_synth_package.tcl") -Destination (Join-Path $packageRoot "scripts\vivado_synth_package.tcl") -Force
Copy-Item -LiteralPath (Join-Path $repoRoot "scripts\list_xc7z_parts.tcl") -Destination (Join-Path $packageRoot "scripts\list_xc7z_parts.tcl") -Force

$manifest = @"
# P201Pro 2T2R SD Project Manifest

Generated: $generatedAt

This package is a staged FPGA/SD experiment project for P201Pro 2T2R work.
It is not a ready-to-boot SD card image yet.

Contents:
- hdl/: generated Verilog feasibility core
- scripts/: Vivado verification/synthesis scripts
- reports/: synthesis and validation evidence
- sd_overlay/: placeholder for later copied SD-card overlay files
- vivado_project/: reserved for generated Vivado project/IP integration

Safety:
- Do not copy this onto the original SD boot directory directly.
- Use only a copied SD card or copied boot directory for experiments.
- No BOOT.bin or bitstream is included until Vivado integration is verified.
"@
Set-Content -LiteralPath (Join-Path $packageRoot "MANIFEST.md") -Value $manifest -Encoding UTF8

$readme = @"
# P201Pro 2T2R SD Experiment Project

This folder is the current handoff package for the P201Pro Zynq-7020 SDR FPGA preprocessing work.

## Current State

The package contains a generated Verilog feasibility core for the first acceleration stage:

```text
IQ/power bins -> PSD-like power outputs -> peakPower/sumPower
```

It does not yet contain a vendor-integrated bitstream, BOOT.bin, device tree update, or complete SD boot image.

## How To Use Safely

1. Keep the original SD boot folder untouched:

```text
C:\Users\20642\Desktop\开发\SDR\2r2t
```

2. Use this package only as an experiment source for a copied SD boot workspace or a new card.

3. First verify the Vivado part database:

```powershell
& 'E:\Xilinx\Vivado\2019.1\bin\vivado.bat' -mode batch -nolog -nojournal -notrace -source scripts/list_xc7z_parts.tcl
```

4. Run synthesis from an ASCII-only path if Vivado crashes under Chinese paths:

```powershell
Copy-Item -Recurse -Force . E:\vivado\p201pro_2t2r_sd_project
cd E:\vivado\p201pro_2t2r_sd_project
& 'E:\Xilinx\Vivado\2019.1\bin\vivado.bat' -mode batch -source scripts/vivado_synth_package.tcl
```

## Next Integration Step

The next real integration task is to wrap this HDL into an AXI-Stream/AXI-Lite friendly IP and merge it into the vendor P201Pro Vivado/boot flow. Do not replace BOOT.bin before that integration is verified.
"@
Set-Content -LiteralPath (Join-Path $packageRoot "README.md") -Value $readme -Encoding UTF8

New-Item -ItemType Directory -Force -Path $asciiWorkRoot | Out-Null
Copy-Item -Path (Join-Path $packageRoot "*") -Destination $asciiWorkRoot -Recurse -Force

[pscustomobject]@{
    PackageRoot = $packageRoot
    AsciiWorkRoot = $asciiWorkRoot
    GeneratedAt = $generatedAt
}
