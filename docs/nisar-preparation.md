# NISAR GCOV extension (experimental)

Source `nisar_gcov`, profile `nisar-gcov-validated-a-20m-100m-v1` uses
`NISAR_L2_GCOV_V1`, frequency A only, from 2026-10-21. No V1 changes.
Use `sm-benchmark-prepare` with matching SRTM/HWSD2/MCD12Q1 contexts, the
same source registry and annual/date-scoped assembly used by other sources.
Example: [request](../configs/nisar-request.example.json).

Install the `nisar` extra using the selected interpreter. Earthdata authentication
uses the existing home `.netrc` entry for urs.earthdata.nasa.gov; see
[Earthdata setup](smap-l3-preparation.md#earthdata-setup). It is separate from
GEE; `credential_ref` is not opened by this source. Never put secrets in requests.

Discovery is offline during planning and happens only during accepted execution.
Up to 64 scenes are discovered; overflow fails rather than truncates. `0005`
scenes without A are recorded as skipped. There is no B or full-HDF5 fallback.
Per scene attempt: at most 96 MiB/128 ranges; outer transient fetch retries are
bounded to two. Auth/permission/quota failures stop without account switching.
Unknown transfer volume is reported as unknown, not zero.

Original 10/20 m A layers go to nominal 20 m EPSG:6933 (650 x 650); original
80 m goes to nominal 100 m (130 x 130), with identical bounds. Diagonal
covariance powers are retained, plus mask, inputDataExceptionMask, numberOfLooks
and rtcGammaToSigmaFactor. Polarizations are discovered, not forced to HH/HV.
Power and continuous auxiliary layers use area averaging; QA uses nearest.
Declared fills become NaN, zero power remains valid, no temporal interpolation.
Nearest QA is not a summary of all source contributors. Averaged looks/factors
are descriptive, not effective looks or exact conversions after averaging.
No additional QA screening, sigma0 generation, or covariance off-diagonal terms.

Discovery/profile/code identities and per-scene SHA-256 receipts are durable.
Completed scene folders are published atomically and revalidated on restart.
Annual metadata and raster assets assemble once through the unified workflow;
source state is conservatively `partial` because QA remains user-selectable.
Empty/absent-A source queries are explicit `unavailable`, never provider errors.
No scheduler service or automatic machine-reboot recovery is installed.

See [recorded live tests and limitations](nisar-development.md). Live 10, 20
and 80 m A window reads passed; generic global/annual completeness, clean install,
and cross-model behavior are not established by these samples.
