repoRoot = fileparts(fileparts(mfilename("fullpath")));
addpath(fullfile(repoRoot, "matlab"));
reportsDir = fullfile(repoRoot, "reports");
if ~exist(reportsDir, "dir")
    mkdir(reportsDir);
end

reportPath = fullfile(reportsDir, "psd_reference_tests.txt");
if exist(reportPath, "file")
    delete(reportPath);
end
diary(reportPath);
fprintf("P201Pro PSD reference tests\n");
fprintf("Generated: %s\n", datestr(now, 31));
fprintf("MATLAB version: %s\n\n", version);

sampleRateHz = 1.0e6;
centerFreqHz = 433.92e6;
fftLen = 1024;
avgFrames = 4;
n = (0:(fftLen * avgFrames - 1)).';

singleOffsetHz = 125e3;
singleIq = exp(1j * 2 * pi * singleOffsetHz / sampleRateHz .* n);
singleResult = p201pro_psd_reference(singleIq, sampleRateHz, centerFreqHz, fftLen, avgFrames);
singleErrorHz = abs(singleResult.peakOffsetHz - singleOffsetHz);
fprintf("SINGLE_TONE peak_offset_hz=%.3f expected_hz=%.3f error_hz=%.3f\n", ...
    singleResult.peakOffsetHz, singleOffsetHz, singleErrorHz);
assert(singleErrorHz <= sampleRateHz / fftLen, "Single-tone peak frequency error too high.");

multiOffsetsHz = [-180e3, 210e3];
multiIq = 0.8 .* exp(1j * 2 * pi * multiOffsetsHz(1) / sampleRateHz .* n) + ...
    1.2 .* exp(1j * 2 * pi * multiOffsetsHz(2) / sampleRateHz .* n);
multiResult = p201pro_psd_reference(multiIq, sampleRateHz, centerFreqHz, fftLen, avgFrames);
[~, order] = sort(multiResult.psdDb, "descend");
topOffsets = sort(multiResult.freqAxisHz(order(1:8)) - centerFreqHz);
hit1 = any(abs(topOffsets - multiOffsetsHz(1)) <= sampleRateHz / fftLen);
hit2 = any(abs(topOffsets - multiOffsetsHz(2)) <= sampleRateHz / fftLen);
fprintf("MULTI_TONE top_offsets_hz=%s\n", mat2str(topOffsets.', 5));
assert(hit1 && hit2, "Multi-tone peaks were not found in top PSD bins.");

rng(20260606);
noiseIq = (randn(size(n)) + 1j .* randn(size(n))) ./ sqrt(2);
noiseResult = p201pro_psd_reference(noiseIq, sampleRateHz, centerFreqHz, fftLen, avgFrames);
noiseSpreadDb = localPercentile(noiseResult.psdDb, 95) - localPercentile(noiseResult.psdDb, 5);
fprintf("NOISE spread_db_5_to_95=%.3f\n", noiseSpreadDb);
assert(isfinite(noiseSpreadDb) && noiseSpreadDb < 20, "Noise PSD average is unexpectedly unstable.");

save(fullfile(reportsDir, "psd_reference_test_vectors.mat"), ...
    "sampleRateHz", "centerFreqHz", "fftLen", "avgFrames", ...
    "singleIq", "singleResult", "multiIq", "multiResult", "noiseResult");
fprintf("\nPSD_REFERENCE_TESTS=PASS\n");
diary off;

function value = localPercentile(x, pct)
x = sort(double(x(:)));
idx = 1 + (numel(x) - 1) * pct / 100;
lo = floor(idx);
hi = ceil(idx);
if lo == hi
    value = x(lo);
else
    value = x(lo) + (x(hi) - x(lo)) * (idx - lo);
end
end
