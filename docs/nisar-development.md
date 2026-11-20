# NISAR GCOV development status

Experimental GCOV adapter. The unified registry now supports the fixed Validated
frequency-A profile described in [preparation](nisar-preparation.md). Not in V1.
Earlier prototype-only limitations below are historical evidence.

`python -m sm_benchmark_agent.nisar_discovery --anchor-id ANCHOR --start DATE
--end DATE --maturity validated --limit 16` performs bounded CMR discovery.
Choose exactly one maturity; Beta, Provisional and Validated are never combined.
Date endpoints are inclusive UTC within one year. Excess results cause failure,
not silent truncation. Discovery does not require authentication.

`nisar_http.NISARRangeFS` provides authenticated-session, read-only HDF5 byte
ranges with explicit transfer/request budgets. Ignored ranges, untrusted URLs
and budget exhaustion stop; there is no whole-scene fallback. Credentials and
signed links must not enter public metadata. Seven offline tests cover
discovery boundaries, identity/link checks, transport rejection paths and grids.

## Approved two-grid delivery profile

Original 10/20 m layers are reprojected to the nominal 20 m EPSG:6933 context
(650 x 650). Original 80 m layers go to the nominal 100 m context (130 x 130).
These grids have identical bounds and nest at 5 x 5. Spacing labels are nominal;
exact spacing is derived from the established EASE2 M01km lattice. Frequency
A/B, polarization, original posting and effective spatial support remain distinct.
No 80 m data are upsampled to the 20 m grid. Current development scope is
frequency A only. Frequency B retrieval is excluded, including for live tests.

Power is area-averaged in linear gamma0 units; categorical QA uses nearest
neighbor and is explicitly not a summary of every contributing source pixel.
Provider fill becomes NaN, valid zero power is retained. QA codes are preserved
without imposing an unverified science-screening rule. Auxiliary factor/looks
averages must not be interpreted as an exact gamma0-to-sigma0 conversion factor
or effective output number of independent looks. No sigma0 is generated.

On 2026-11-19 a live metadata query at EASE2_M09km_R0285_C3179 for
2026-11-01 through 2026-11-07 returned two Validated GCOV products. The first
product returned HTTP 206 for an authenticated range. Its HDF5 metadata was read
using four requests and 3,145,729 bytes instead of downloading the 2,109,734,912
byte scene. Frequency A has 20 m posting in EPSG:32650 and HHHH/HVHV power
layers, mask, inputDataExceptionMask, numberOfLooks and rtcGammaToSigmaFactor.
Subsequent bounded native-window extraction succeeded for HHHH, HVHV, mask and
inputDataExceptionMask (744 x 578). Transfer was 15,728,641 bytes in 16 requests.
This does not yet establish fully validated two-grid delivery.

The same real frequency-A window was subsequently reprojected to the exact
nominal 20 m context: four layers, 650 x 650, EPSG:6933, with 422,500 finite
pixels in each layer after declared fill decoding. QA remains unfiltered provider
codes. The 80-to-100 m route currently has synthetic grid/value tests only;
frequency-B live processing is not claimed and is not in the implementation plan.

Remaining gates: full official QA semantics, live 80-to-100 m reprojection,
explicit frequency and
polarization selection, checkpoint validation, unified assembly and live annual
delivery. Do not label provider failures as missing observations or upsample
80 m frequency-B data as independent 20 m information.

References: [GCOV](https://nisar-docs.asf.alaska.edu/gcov/),
[GDAL access](https://nisar-docs.asf.alaska.edu/gdal/).
Older GDAL HDF5 drivers do not decode NISAR CF georeferencing; the official
guide specifies the netCDF driver before GDAL 3.13. The prototype instead reads
explicit coordinate datasets without assuming an HDF5 driver geotransform.

## Two-scene acceptance, 2026-11-20 (Asia/Shanghai)

Two Validated frequency-A GCOV scenes at the same anchor were retrieved for
2026-11-01 and 2026-11-05. Window reads transferred 24,117,249 and 42,991,617
bytes in 24 and 42 requests, respectively. No frequency-B raster was read and
neither full HDF5 scene was downloaded. Each produced six float32 layers at
650 x 650 in EPSG:6933: HHHH, HVHV, mask, inputDataExceptionMask, numberOfLooks
and rtcGammaToSigmaFactor. Provider fill attributes were decoded; each layer
had 422,500 finite pixels. Finite QA is not a declaration of scientific validity.

A station-free two-scene package passed complete member/CRC/size/hash validation
and relocated archive verification. Package size is 13,108,704 bytes; SHA-256
`403acba3614f1528fb35e5d390da8109bdb1d35cd35201eb3ab79f7826be4cb4`.
Replay with all requests Session.request operations blocked succeeded from
checksummed processed outputs. This is a cache replay test, not interruption
recovery inside an unfinished HDF5 read. Test data/logs remain checkout-local.

Ten focused tests now cover all three original spacings using frequency-A-only
HDF5 fixtures, non-integer area weights, native fills/zero power, integer QA,
transport budgets, ignored/truncated ranges and bounded discovery. Real 10 m
and 80 m frequency-A cases remain untested. The prototype is not registered as
a supported adapter, does not yet use unified preparation/context assembly, and
does not support annual unattended acquisition. V1 and GitHub were unchanged.

## Bandwidth is not an application label

Frequency-A bandwidth controls range resolution, not a wholly different
geophysical measurement. Wider bandwidth generally resolves finer range detail;
mission mode selection also balances data volume, swath and polarization needs.
Background-land/soil-moisture modes commonly use 20+5 MHz, higher-detail urban
and some North American modes use 40+5 MHz, high-resolution land-ice modes use
the widest band, and low-bandwidth modes support e.g. sea-ice/background needs.
These are observation-strategy examples, not immutable global mode assignments
or exclusive uses. Consult current acquisition metadata and observation plans.
77 MHz GCOV is posted to 20 m, so widest bandwidth does not imply the finest
distributed pixel spacing. Bandwidth, center frequency, polarization, original
posting, processing maturity and orbit must remain identifiable after resampling.

References: [observation strategy](https://science.nasa.gov/mission/nisar/observation-strategy/),
[observation plan](https://nisar-docs.asf.alaska.edu/observation-plan/),
[GCOV posting table](https://nisar-docs.asf.alaska.edu/gcov/).

## Real 10 m acceptance, 2026-11-20

A Validated 40+5 MHz scene acquired 2026-11-04 at 11:54:36 UTC was tested over
EASE2_M09km_R0305_C0851 (Kansas area). Frequency A declares 10 m posting in
EPSG:32614. All six selected A layers were read by bounded ranges, with no B
layer access, then reprojected to the nominal 20 m context (650 x 650).
Transfer: 56,623,105 bytes in 55 requests. Compressed output: 6,463,970 bytes.
All six layers have 422,500 finite output pixels; discrete QA remained integer.
Output SHA-256: `5ee7ceb3ce8aa341b4de326ce0c18881e90d8441cc3c58cebe06601890cccab2`.
The 10 m route now has one live case, in addition to two live 20 m cases.
Frequency-A 80 m remains synthetic-only. Finite values do not imply QA acceptance.

## Real 80 m acceptance, 2026-11-20

The remaining branch subsequently passed a bounded live test at
EASE2_M09km_R0052_C0695 in northern Canada. The Validated 2026-11-01 04:18:28 UTC
scene has mode 0505/SVSH: frequency A is 5 MHz VV, posted at 80 m in EPSG:3413.
Only A datasets were accessed. VVVV and four auxiliary layers were reprojected
to nominal 100 m EPSG:6933, 130 x 130, using the approved two-grid rules.
All five layers have 16,900 finite pixels; QA codes remain integers. Transfer
was 12,582,913 bytes in 13 requests; the compressed output is 187,591 bytes.
SHA-256: `bb4c20ec1a0d68c1920dd1e2bfd34f2db78707b8bde7419f74fbe8ae134c89b2`.
This validates a polar-projection/single-polarization transport and reprojection
case, not suitability of this location for land soil-moisture retrieval.

Initial Sahara search results included 0005/NASV products (no A acquisition).
Those are B-only and were not read as an 80 m A test. Future source discovery
must distinguish absent-A scenes rather than interpret all 5 MHz data as A.
All three original posting branches now have real examples; annual scheduling,
production QA exclusions, robust checkpoint management and unified adapter
registration remain pending. Ten focused offline tests were rerun successfully.

## Unified adapter acceptance, 2026-11-20

The fixed Validated frequency-A profile is now registered in the default adapter
registry and skill index. Default-adapter live execution for 2026-11-01 at
EASE2_M09km_R0285_C3179 succeeded, then checksum/grid validation and a replay
with sockets blocked succeeded. Atomic scene checkpoints and offline resume
after a simulated second-scene failure passed; corrupt cached output is refused.
The unified planner/exporter packaged the real cached GCOV output with synthetic
context fixtures and passed relocated ZIP checks with network blocked. This is
not a live static-context acquisition test. Public files exclude data URLs,
provider account details and private paths. Short hash filenames avoid Windows
path limits while full source identities remain in metadata.

Thirteen focused NISAR tests passed, covering absent-A discovery, pre-Validated
coverage, two-grid processing, transfer bounds, interruption recovery, corruption,
unified delivery and reuse. A wheel build and installed-wheel registry check
passed. Scope remains experimental; no annual/global completeness, machine-reboot
service or cross-model acceptance is inferred. V1 is unchanged.

The full existing-environment regression run passed 126 tests; the final focused
NISAR run passed 13 (including the subsequently added absent-A coverage test).
The new skill passed frontmatter validation and all 15 source routes resolved.
