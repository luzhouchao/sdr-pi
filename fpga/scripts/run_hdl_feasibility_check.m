repoRoot = fileparts(fileparts(mfilename("fullpath")));
addpath(fullfile(repoRoot, "matlab"));
reportsDir = fullfile(repoRoot, "reports");
if ~exist(reportsDir, "dir")
    mkdir(reportsDir);
end

reportPath = fullfile(reportsDir, "hdl_feasibility_check.txt");
if exist(reportPath, "file")
    delete(reportPath);
end
diary(reportPath);
fprintf("P201Pro HDL feasibility check\n");
fprintf("Generated: %s\n", datestr(now, 31));
fprintf("MATLAB version: %s\n\n", version);

N = 64;
n = (0:(N - 1)).';
toneBin = 7;
iq = exp(1j * 2 * pi * toneBin / N .* n);
iIn = fi(real(iq), 1, 16, 14);
qIn = fi(imag(iq), 1, 16, 14);
[peakIndex, peakPower, psdOut] = p201pro_psd_core_hdl(iIn, qIn);
fprintf("CORE_SIM peak_index=%d expected=%d peak_power=%.6f\n", ...
    double(peakIndex), toneBin + 1, double(peakPower));
assert(double(peakIndex) == toneBin + 1, "HDL candidate peak bin mismatch.");
assert(all(isfinite(double(psdOut))), "HDL candidate PSD contains non-finite values.");

try
    hdlsetuptoolpath("ToolName", "Xilinx Vivado", ...
        "ToolPath", "E:\Xilinx\Vivado\2019.1\bin\vivado.bat");
    fprintf("Vivado toolpath: PASS\n");
catch ME
    fprintf("Vivado toolpath: FAIL\n%s\n", getReport(ME, "basic"));
end

fprintf("HDL_FEASIBILITY_NUMERIC_SIM=PASS\n");
fprintf("NOTE: Direct DFT core is for HDL interface feasibility only; production should replace it with FFT IP.\n");
diary off;
