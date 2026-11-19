# HLS S30 extension (experimental)

Source `hls_s30`, profile `hls-s30-v2-50m-screened-v1`, collection **HLSS30 2.0**.
Opt-in agent extension only, not an addition to fixed V1. Native Sentinel-2 L2A,
HLS L30, angles and derived vegetation indices are excluded from this profile.
HLS includes BRDF and spectral adjustments, not just spatial resampling.

## Scientific profile

Ten unitless reflectance bands B02/B03/B04/B05/B06/B07/B08/B8A/B11/B12 and Fmask.
Apply reflectance scale 0.0001, independent of optional TIFF scale tags. Exclude
-9999 fill, 12000 saturation, Fmask 255, cloud (bit 1), adjacent cloud/shadow (2),
cloud shadow (3), snow/ice (4), and high aerosol (bits 6 and 7 both set). Retain
water and negative non-fill reflectance. This policy is fixed and versioned.

Mask on the native 30 m grid BEFORE average reprojection to the exact nominal
50 m EPSG:6933 context (260 x 260). Fmask uses nearest neighbor, describing the
nearest source pixel, not all contributors to a reflectance average. No minimum
clear-area fraction is imposed; a valid mean may have sparse clear support.

Each granule yields one compressed 11-band float32 TIFF. Missing values are NaN
in all layers; valid Fmask values remain exact integer codes. Overlapping MGRS
tiles remain separate, not independent overpasses. No temporal composites or
interpolation. Public manifests record granule IDs/times, units, band order,
checksums, valid counts and processing rules. Availability describes retrieved
granules, not complete daily coverage.
Times use CMR `time_start`, not the time embedded in the granule filename, which
can differ by several minutes. Both the full ID and actual start are retained.

## Setup and execution

Use [Python setup](python-environment.md), install the `hls` extra, and configure
the home `.netrc` entry as in [Earthdata setup](smap-l3-preparation.md#earthdata-setup).
The provider uses `earthaccess.login(strategy='netrc', persist=False)` and
authenticated HTTPS COG window reads via its requests session and a bounded
synchronous range reader, using Rasterio's opener interface (>=1.4). Each range
must return HTTP 206 with the requested bounds; responses that ignore ranges
are rejected. Blocks are cached in memory. Tokens never enter public metadata.
`credential_ref` is not read by HLS; mixed sources may still need GEE configuration.
Human login/service authorization remains with the user. Harmony authentication
alone is not proof of LP DAAC access.

Use [this request](../configs/hls-request.example.json) with the existing
`sm-benchmark-prepare --request ... --context-plan ... --asset-root ...` command.
Review offline, then execute the unchanged plan using `--execute --accept-plan`.
The unified workflow still requires all three reviewed context sources; explain
these prerequisites before preparation. It assembles all selected sources once.

Discovery is bounded to 512 granules and exact dates/context. Each of 11 layers
has a maximum 2048 x 2048 native window. HTTP request count and transfer volume
depend on COG block layout and remain unknown, not zero. No full-tile fallback.
The unified registry uses bounded range retries described below; outer transient
operations have two retries. Auth/quota failures stop. Checksummed
processed granules are retained for restart. Antimeridian contexts are unsupported.
Files enter `annual/hls_s30/` with a source manifest. Use a distinct extension
release and output root, never rewrite V1.

## Evidence and limits

Synthetic tests cover masking/scaling, reprojection, QA preservation, exact dates,
checkpoint recovery, corrupt-cache rejection and unified ZIP delivery. Real
authenticated annual retrieval has now passed for the case recorded below.
Global coverage, fresh installation and model-agent trials remain separate
acceptance gates. This remains an experimental extension.

On 2026-11-17, a live CMR query for the example anchor and 2020-06-01 through
2020-06-07 returned eight granules. An authenticated HTTPS range request for
one B02 COG returned HTTP 206 with a TIFF header. Complete native COG window
processing did not pass: a GDAL read failed, and a subsequent attempt encountered
Earthdata login timeout/TLS failures. A native window-indexing DLL failure was
also isolated and removed by using scalar indexing on the checked north-up grid.
The final route uses the authenticated filesystem opener, not direct GDAL curl.
At that stage neither complete live preparation nor live delivery had passed.
Mocked native-UTM raster tests were separate from that online evidence.
The regression suite passed 106 tests; the five HLS tests additionally passed
after the final provider changes. Skill routing and frontmatter validation passed.
Test dependencies were installed in an ignored temporary environment; the existing
production environment and its download jobs were not upgraded or restarted.

Subsequent live acceptance at EASE2_M09km_R0285_C3179 for the first 2022 granule
passed using an isolated HLS environment and the synchronous range transport.
All eleven layers produced a 260 x 260 raster; each reflectance band had 54,330
valid pixels and Fmask had 67,599. Annual discovery returned 119 granules. This
established one-granule retrieval/processing; annual completion is recorded below.
The asynchronous transport was replaced after failed/hanging reads; no scientific
masking or resampling rules changed. Context validation now tolerates 1e-7 degree
inverse-PROJ differences in center coordinates while retaining exact projected
grid and anchor identity checks.

References: [HLS products](https://hls.gsfc.nasa.gov/data-products/),
[S30](https://hls.gsfc.nasa.gov/products-description/s30/),
[access](https://hls.gsfc.nasa.gov/data-access-and-tools/),
[earthaccess](https://earthaccess.readthedocs.io/en/latest/api/).

## Resilient transport

The unified registry now injects `hls_resilience.ResilientEarthdataHLS` into
`HLSAdapter`; direct adapter callers can also inject it without
changing masking, resampling, discovery or granule validation. It retries a
truncated range, timeout, connection failure or HTTP 408/500/502/503/504 up to
four times with 5/10/20/40-second delays. The same range is requested each time;
full-tile fallback is still forbidden. HTTP 401/403/429 and malformed range
responses stop for review. Operations record the transport module hash separately
from existing scientific checkpoint hashes, preserving verified granule reuse.

The local 2022 acceptance job additionally uses a single-worker supervisor with
5/15/30/60-minute restart backoff, capped at eight restarts without progress.
Only classified transient failures qualify; unknown, authentication and quota
failures stop. A pause marker prevents subsequent restarts. The detached process
survives chat disconnection, not machine shutdown; its persisted state supports
manual restart after reboot. This is local job supervision, not yet an installed
cross-platform service. Unit tests cover
short-response recovery, bounded timeout retries, and auth/quota/malformed-response
stops. No GEE accounts or V1 data are involved.

## Annual live acceptance (2026-11-19)

At `EASE2_M09km_R0285_C3179`, all 119 discovered HLSS30 v2.0 granules for
2022 were retrieved, screened and processed. Acquisition timestamps span
2022-01-02 to 2022-12-30, with granules in all twelve months. Every output has
11 float32 bands on the exact 260 x 260 EPSG:6933 context grid. Of these,
32 granules have no eligible reflectance after screening; the annual source
remains `partial`, not a gap-free daily series. The ten reflectance bands and
Fmask retain the profile documented above.

The HLS/context package contains 132 files and is 130,645,456 bytes. Complete
member/CRC/size/SHA-256 validation passed. Archive SHA-256:
`07cf9790e6f3cdd5c074f8e9e9cbd2d7fc60c0f7fb25ac5d530cc721b57d3bc0`.

A separately authorized local augmentation of an existing same-anchor/year
multi-source package also passed: 155 files, 154,366,254 bytes, with all 32
original members other than README and package manifest preserved byte-for-byte.
Archive SHA-256:
`8f933fbfb38978a8618302432d47fb7a6cb4378161f436556cb153ff902ed857`.
That augmentation was a local delivery check, not a newly supported generic
ZIP-merge CLI. Normal public preparation uses unified source assembly. Neither
package contains station targets, and no fixed V1 archive was changed.

The live run used the same resilient provider via injection and a local
supervisor. Default-registry wiring is covered separately by offline tests.
This single case does not establish global coverage, unattended reboot recovery,
or clean-environment/cross-model acceptance. Data archives are not shipped in Git.

Public-update regression checks on 2026-11-19 passed 114 tests in the existing
Conda scientific environment (launched with `conda run`), plus 12 focused HLS
tests in the isolated Rasterio/earthaccess runtime. Wheel build and installed-wheel
HLS registry checks passed. These are existing-environment tests, not a fresh
Conda installation acceptance claim.
