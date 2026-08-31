repoRoot = fileparts(fileparts(mfilename("fullpath")));
reportsDir = fullfile(repoRoot, "reports");
if ~exist(reportsDir, "dir")
    mkdir(reportsDir);
end

vivadoPath = "E:\Xilinx\Vivado\2019.1\bin\vivado.bat";
sdBootDir = "C:\Users\20642\Desktop\开发\SDR\2r2t";
vendorRoot = "G:\ROS开发\SDR P201P";

diaryFile = fullfile(reportsDir, "environment_freeze.txt");
if exist(diaryFile, "file")
    delete(diaryFile);
end
diary(diaryFile);
fprintf("P201Pro FPGA SDR acceleration environment freeze\n");
fprintf("Generated: %s\n\n", datestr(now, 31));
fprintf("MATLAB version: %s\n", version);
fprintf("MATLAB root: %s\n", matlabroot);
fprintf("Vivado path: %s\n", vivadoPath);
fprintf("Vendor root: configured P201Pro package path on G: drive; see HANDOFF.md for Unicode path.\n");
fprintf("SD boot reference: configured 2r2t SD boot path; see HANDOFF.md for Unicode path.\n\n");

try
    hdlsetuptoolpath("ToolName", "Xilinx Vivado", "ToolPath", vivadoPath);
    fprintf("hdlsetuptoolpath: PASS\n");
catch ME
    fprintf("hdlsetuptoolpath: FAIL\n%s\n", getReport(ME, "basic"));
end

fprintf("\nRelevant toolbox versions:\n");
toolboxes = ver;
keywords = ["simulink", "hdl", "fixed-point", "dsp", "communications"];
for k = 1:numel(toolboxes)
    name = lower(string(toolboxes(k).Name));
    if any(contains(name, keywords))
        fprintf("- %s | %s\n", toolboxes(k).Name, toolboxes(k).Version);
    end
end

fprintf("\nSD boot file SHA-256:\n");
files = ["BOOT.bin", "devicetree.dtb", "uEnv.txt", "uImage", "uramdisk.image.gz"];
for k = 1:numel(files)
    path = fullfile(sdBootDir, files(k));
    if exist(path, "file")
        hash = localFileSha256(path);
        info = dir(path);
        fprintf("- %s | bytes=%d | sha256=%s\n", files(k), info.bytes, hash);
    else
        fprintf("- %s | MISSING\n", files(k));
    end
end
diary off;

function hash = localFileSha256(path)
md = java.security.MessageDigest.getInstance("SHA-256");
fis = java.io.FileInputStream(char(path));
cleanup = onCleanup(@() fis.close());
buf = zeros(1, 1048576, "uint8");
while true
    n = fis.read(buf, 0, numel(buf));
    if n < 0
        break;
    end
    md.update(buf, 0, n);
end
bytes = typecast(md.digest(), "uint8");
hash = lower(reshape(dec2hex(bytes).', 1, []));
end
