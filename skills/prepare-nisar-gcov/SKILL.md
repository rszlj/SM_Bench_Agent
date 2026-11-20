---
name: prepare-nisar-gcov
description: Prepare NISAR L2 GCOV Validated frequency-A backscatter for soil-moisture benchmark extensions. Excludes frequency B, Beta/Provisional mixing and fixed V1 backfill.
---

# Prepare GCOV

Read [execution rules](../shared/execution.md) and
[GCOV preparation](../../docs/nisar-preparation.md).

- Use `nisar_gcov` through unified preparation with matching reviewed contexts.
- Install the `nisar` extra in the selected environment. Reuse Earthdata home
  `.netrc` login; no new GEE project is needed for GCOV itself.
- Validated collection only, coverage starts 2026-10-21. Do not replace older
  dates with Beta/Provisional without a separately reviewed profile.
- Frequency A only. `0005` is absent-A, not an 80 m A observation. Retain
  polarization and native spacing; 10/20 -> 20 m, 80 -> 100 m, common bounds.
- Explain gamma0 linear power, provider QA preservation and descriptive
  averaged auxiliary fields. Do not imply all finite values pass science QA or
  multiply averaged gamma0 by averaged factors to claim exact sigma0.
- Start with a short period. Limit 64 discovered scenes; each attempt is bounded
  to 96 MiB and 128 ranges. Never fall back to whole-scene downloads or B.
- Resume validated scene checkpoints. Corrupt caches/code changes require
  inspection, not silent redownload. No unattended reboot recovery is installed.

Return the validated package, explicit gaps and actual acceptance scope.
