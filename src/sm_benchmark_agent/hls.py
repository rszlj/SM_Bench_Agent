"""Experimental HLS S30 v2.0 profile, CMR discovery and local COG processing.

No GEE dependency and no V1 backfill. Granules remain separate (including tile
overlaps); this is not a unique-overpass or daily composite product.
"""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import urlopen

from . import periods
from .grid import anchor_cell_from_id, context_grid, ContextResolution
from .processing.srtm import _expanded_wgs84_bounds

PROFILE = 'hls-s30-v2-50m-screened-v1'
BANDS = ('B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B08', 'B8A', 'B11', 'B12')
LAYERS = (*BANDS, 'Fmask')
MAX_GRANULES = 512
MAX_WINDOW = 2048
PATTERN = re.compile(r'HLS\.S30\.T[0-9]{2}[A-Z]{3}\.(\d{7}T\d{6})\.v2\.0')


def grid(unit):
    return context_grid(anchor_cell_from_id(unit.anchor_id), ContextResolution('50 m', 20))


def transform(unit):
    from affine import Affine
    g = grid(unit)
    return Affine(g.exact_spacing_m, 0, g.upper_left_x_m, 0, -g.exact_spacing_m, g.upper_left_y_m)


def profile(unit):
    return dict(source_id='hls_s30', profile_id=PROFILE, collection='HLSS30', version='2.0',
                anchor_id=unit.anchor_id, year=unit.year, **periods.metadata(unit),
                target_grid=asdict(grid(unit)), bands=list(LAYERS),
                units={**{b: '1' for b in BANDS}, 'Fmask': 'bit field'},
                reflectance='HLS NBAR; scale 0.0001; not native Sentinel-2 L2A',
                quality_policy='exclude fill, saturation 12000, cloud, adjacent cloud/shadow, cloud shadow, snow/ice and high aerosol; retain water',
                resampling='valid source reflectance mean; Fmask nearest neighbor (not a summary of contributing pixels)',
                temporal_support='individual source granules; overlapping tiles retained separately; no temporal composite',
                missing_policy='NaN in every output band; Fmask valid values retain integer codes',
                extension_only=True)


def checked_records(records, unit):
    if not isinstance(records, list) or len(records) > MAX_GRANULES:
        raise ValueError('HLS granule limit exceeded; split requested dates')
    seen = set()
    for r in records:
        if set(r) != {'id', 'time'} or not PATTERN.fullmatch(r['id']) or r['id'] in seen:
            raise ValueError('Invalid or duplicate HLS granule')
        nominal = datetime.strptime(PATTERN.fullmatch(r['id'])[1], '%Y%jT%H%M%S').replace(tzinfo=timezone.utc)
        stamp = datetime.fromisoformat(r['time'])
        if (stamp.tzinfo is None or stamp.utcoffset().total_seconds() != 0
                or not periods.contains(unit, stamp) or abs((stamp-nominal).total_seconds()) > 86400):
            raise ValueError('HLS acquisition outside requested dates or inconsistent identity')
        seen.add(r['id'])
    return sorted(records, key=lambda r: (r['time'], r['id']))


def process(arrays, source_transform, source_crs, unit):
    """Mask BEFORE averaging. Keep valid negative reflectances; no clipping to 0..1."""
    import numpy as np
    from rasterio.warp import reproject, Resampling
    if set(arrays) != set(LAYERS):
        raise ValueError('HLS input layers incomplete')
    qa = np.asarray(arrays['Fmask'])
    if qa.ndim != 2 or not 0 < min(qa.shape) <= max(qa.shape) <= MAX_WINDOW:
        raise ValueError('HLS source window exceeds bound')
    if any(np.asarray(a).shape != qa.shape for a in arrays.values()):
        raise ValueError('HLS layers are not aligned')
    if not np.isfinite(qa).all() or (qa != np.floor(qa)).any() or ((qa < 0) | (qa > 255)).any():
        raise ValueError('Invalid Fmask codes')
    qa = qa.astype('uint8')
    # Bits 1 cloud, 2 adjacency, 3 shadow, 4 snow; aerosol bits 6/7 == 3.
    eligible = (qa != 255) & ((qa & 30) == 0) & ((qa & 192) != 192)
    result = np.full((len(LAYERS), 260, 260), np.nan, dtype='float32')
    for i, band in enumerate(LAYERS):
        raw = np.asarray(arrays[band])
        if band == 'Fmask':
            values = np.where(qa != 255, qa, np.nan).astype('float32')
        else:
            valid = eligible & np.isfinite(raw) & (raw != -9999) & (raw != 12000)
            values = np.where(valid, raw * 0.0001, np.nan).astype('float32')
        reproject(values, result[i], src_transform=source_transform, src_crs=source_crs,
                  src_nodata=float('nan'), dst_transform=transform(unit), dst_crs='EPSG:6933',
                  dst_nodata=float('nan'), resampling=Resampling.nearest if band == 'Fmask' else Resampling.average)
    return result


class EarthdataHLS:
    """Bounded CMR discovery; authenticated HTTPS range reads, never full-tile fallback."""
    def discover(self, unit):
        start, end = periods.bounds(unit)
        bounds = _expanded_wgs84_bounds(grid(unit), 0)
        if bounds[2] - bounds[0] > 180:
            raise ValueError('Antimeridian HLS contexts require a separate reviewed route')
        query = urlencode({'short_name': 'HLSS30', 'version': '2.0', 'page_size': MAX_GRANULES + 1,
                           'bounding_box': ','.join(map(str, bounds)),
                           'temporal': start.isoformat() + ',' + end.isoformat()})
        with urlopen('https://cmr.earthdata.nasa.gov/search/granules.json?' + query, timeout=60) as response:
            payload = response.read(16 * 1024 * 1024 + 1)
        if len(payload) > 16 * 1024 * 1024:
            raise ValueError('CMR response exceeds limit')
        entries = json.loads(payload)['feed']['entry']
        if len(entries) > MAX_GRANULES:
            raise ValueError('HLS granule limit exceeded; split dates')
        records = []
        for entry in entries:
            name = entry['title']
            match = PATTERN.fullmatch(name)
            if not match:
                raise ValueError('Unexpected HLS product/version')
            stamp = datetime.fromisoformat(entry['time_start'].replace('Z', '+00:00'))
            # CMR temporal endpoints are inclusive; our requests are half-open.
            if periods.contains(unit, stamp):
                records.append({'id': name, 'time': stamp.isoformat()})
        return checked_records(records, unit)

    def fetch(self, unit, item):
        import earthaccess
        import numpy as np
        import rasterio
        from rasterio.windows import Window
        from rasterio.warp import transform_bounds
        from .earthdata_setup import check_local
        if not hasattr(self, 'fs'):
            if check_local()['status'] != 'configured':
                raise ValueError('Earthdata credentials require home .netrc setup')
            # earthaccess defaults to _netrc on Windows; the benchmark contract
            # uses .netrc on every OS. Bind only for this login, never copy secrets.
            previous = os.environ.get('NETRC')
            os.environ['NETRC'] = str(Path.home()/'.netrc')
            try:
                auth = earthaccess.login(strategy='netrc', persist=False)
            finally:
                if previous is None:
                    os.environ.pop('NETRC', None)
                else:
                    os.environ['NETRC'] = previous
            if not auth.authenticated:
                raise ValueError('Earthdata authentication failed')
            from .hls_http import RangeFS
            self.fs = RangeFS(earthaccess.get_requests_https_session())
        name = item['id']
        checked_records([item], unit)
        # Official Earthdata Cloud HTTPS granule layout; no signed URLs in manifests.
        base = 'https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/HLSS30.020/' + name + '/'
        arrays, reference = {}, None
        g = grid(unit)
        box = (g.upper_left_x_m, g.upper_left_y_m - 260*g.exact_spacing_m,
               g.upper_left_x_m + 260*g.exact_spacing_m, g.upper_left_y_m)
        for band in LAYERS:
            url = base + name + '.' + band + '.tif'
            with rasterio.open(url, opener=self.fs.open) as src:
                if src.count != 1 or src.crs is None or not src.crs.is_projected or not (
                        abs(src.transform.a-30) < 1e-6 and abs(src.transform.e+30) < 1e-6
                        and src.transform.b == src.transform.d == 0):
                    raise ValueError('Unexpected HLS native grid')
                signature = (src.crs, src.transform, src.width, src.height)
                if reference is not None and reference != signature:
                    raise ValueError('HLS band grids differ')
                reference = signature
                west, south, east, north = transform_bounds('EPSG:6933', src.crs, *box, densify_pts=21)
                # Native HLS grids were checked north-up above. Scalar affine
                # indexing avoids a NumPy LAPACK dependency for window bounds.
                w = Window((west-src.transform.c)/30, (src.transform.f-north)/30,
                           (east-west)/30, (north-south)/30)
                left, top = max(0, math.floor(w.col_off)-2), max(0, math.floor(w.row_off)-2)
                right = min(src.width, math.ceil(w.col_off+w.width)+2)
                bottom = min(src.height, math.ceil(w.row_off+w.height)+2)
                if right <= left or bottom <= top or max(right-left, bottom-top) > MAX_WINDOW:
                    raise ValueError('HLS granule has no overlap or exceeds window limit')
                window = Window(left, top, right-left, bottom-top)
                arrays[band] = src.read(1, window=window, masked=True).astype('float32').filled(255 if band == 'Fmask' else -9999)
                affine, crs = src.window_transform(window), src.crs
        return process(arrays, affine, crs, unit)
