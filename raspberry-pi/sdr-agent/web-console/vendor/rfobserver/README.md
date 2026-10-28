# RFObserver spectral module

`spectral.py` is unmodified from [RFObserver](https://github.com/NSFCUSWIFTPASS/RFObserver)
commit `12a7836c71db06eb04a0827c01e1dfae145b062e`. Its BSD 3-Clause license
is reproduced in `LICENSE`. The web console embeds this source into a bounded
CPU-only adapter; it uses `compute_psd_grid` and does not start RFObserver's
receiver, GPU worker, or web server. The adapter supplies the otherwise unused
`PSDData` import, limits input to one checked SigMF capture, and requires the
system Python's NumPy and SciPy. The result is relative PSD, not calibrated RF
power or a continuous multi-frequency recording.
