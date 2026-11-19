---
name: prepare-hls-s30
description: Prepare experimental HLS Sentinel-2 S30 v2.0 reflectance through Earthdata and local 50 m processing for benchmark extensions. Not native Sentinel-2 L2A, HLS Landsat L30, or V1 backfilling.
---

# Prepare HLS S30

Read [execution rules](../shared/execution.md) and the
[HLS guide](../../docs/hls-preparation.md). For missing dependencies/login read
[onboarding](../shared/onboarding.md).

- Route `hls_s30` through unified preparation with reviewed matching contexts.
  Select only when requested. Existing V1 archives contain no HLS.
- Disclose the fixed ten-reflectance-band plus Fmask quality-screened profile.
  S30 is 30 m HLS NBAR, not native 10 m Sentinel-2. L30 is not implemented.
- Use Earthdata home `.netrc`, not GEE credentials. Offline plans need no login.
- Start with short dates. Limit is 512 granules; range-request count and bytes
  are unknown. Do not fall back to whole-tile downloads or switch accounts.
- Preserve timestamps and granule IDs. Overlapping tiles remain separate and
  must not be counted as independent overpasses. No temporal composites.
- Mask before spatial averaging. Nearest-neighbor Fmask is not a summary of all
  contributing source pixels. Do not average quality codes.
- Report experimental and live-validation limits. Synthetic success is not
  proof of authenticated COG access, global coverage or download performance.

Return validated extension assets/package and explicit gaps. Never trigger V1
backfilling, global downloads or publishing merely by adding this capability.
