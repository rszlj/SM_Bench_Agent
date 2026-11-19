"""Resumable, extension-only HLS adapter for the unified delivery workflow."""
import json
import os
from pathlib import Path
import tempfile
import time

from .adapters import PreparedSource, SourcePlan, ValidationResult
from .delivery import checksum
from .gldas21 import digest, write_json_exclusive, fetch_with_retry
from . import hls, periods


def code_hashes():
    root = Path(__file__).parent
    return {n: checksum(root/n) for n in ('hls.py', 'hls_http.py', 'hls_adapter.py', 'grid.py', 'periods.py', 'processing/srtm.py')}


def key(unit):
    if unit.source_id != 'hls_s30' or unit.profile_id != hls.PROFILE:
        raise ValueError('Invalid HLS source profile')
    hls.grid(unit)
    return f'{hls.PROFILE}/{unit.anchor_id}/{unit.year}' + periods.suffix(unit)


def inspect(path, unit):
    import numpy as np
    import rasterio
    with rasterio.open(path) as src:
        if (src.crs.to_epsg() != 6933 or (src.count, src.height, src.width) != (11, 260, 260)
                or not src.transform.almost_equals(hls.transform(unit), precision=1e-6)
                or src.descriptions != hls.LAYERS or any(d != 'float32' for d in src.dtypes)
                or src.nodata is None or not np.isnan(src.nodata)):
            raise ValueError('HLS output grid/schema mismatch')
        values = src.read()
        if np.isinf(values).any() or (values == -9999).any():
            raise ValueError('Invalid HLS missing representation')
        qa = values[-1][np.isfinite(values[-1])]
        if ((qa < 0) | (qa >= 255) | (qa != np.floor(qa))).any():
            raise ValueError('HLS quality codes altered')
        return {b: int(np.isfinite(values[i]).sum()) for i, b in enumerate(hls.LAYERS)}


class HLSAdapter:
    source_id, profile_id = 'hls_s30', hls.PROFILE

    def __init__(self, *, provider=None, retries=2, sleep=time.sleep):
        if type(retries) is not int or not 0 <= retries <= 3:
            raise ValueError('Invalid retry limit')
        self.provider, self.retries, self.sleep = provider, retries, sleep

    def _records(self, path, unit):
        doc = json.loads(path.read_text())
        if doc['profile'] != hls.profile(unit) or doc['code'] != code_hashes() or doc['sha256'] != digest(doc['records']):
            raise ValueError('HLS discovery integrity/profile mismatch')
        return hls.checked_records(doc['records'], unit)

    def _prepared(self, unit, root):
        meta = json.loads((root/'manifest.json').read_text())
        return PreparedSource(unit, tuple(root/n for n in meta['assets'])+(root/'manifest.json',), meta)

    def plan(self, unit, *, asset_root):
        work = key(unit)
        root = Path(asset_root)/work
        if (root/'annual').exists():
            self.validate(self._prepared(unit, root/'annual'))
            return SourcePlan(unit, 'reusable', 'validated_prepared_source', work, 0, 0)
        if unit.year < 2015:
            return SourcePlan(unit, 'unavailable', 'outside_product_period', work, 0, 0)
        if (root/'discovery.json').exists():
            self._records(root/'discovery.json', unit)
        return SourcePlan(unit, 'retrievable', 'experimental; at most 512 granules, 11 layers each; range-request count and bytes unknown', work, None, None)

    def prepare(self, plan, *, output_root, credential_ref=None):
        import numpy as np
        import rasterio
        unit = plan.unit
        if plan.work_key != key(unit):
            raise ValueError('HLS plan identity mismatch')
        root = Path(output_root)/key(unit)
        annual = root/'annual'
        if annual.exists():
            result = self._prepared(unit, annual)
            self.validate(result)
            return result
        if unit.year < 2015:
            raise ValueError('HLS outside product period')
        root.mkdir(parents=True, exist_ok=True)
        provider = self.provider or hls.EarthdataHLS()
        discovery = root/'discovery.json'
        if not discovery.exists():
            records = hls.checked_records(fetch_with_retry(lambda: provider.discover(unit), retries=self.retries, sleep=self.sleep), unit)
            write_json_exclusive(discovery, dict(profile=hls.profile(unit), code=code_hashes(), records=records, sha256=digest(records)))
        records = self._records(discovery, unit)
        assets, counts = {}, {}
        for item in records:
            name = item['id']+'.tif'
            target = root/'granules'/item['id']
            if not target.exists():
                values = fetch_with_retry(lambda: provider.fetch(unit, item), retries=self.retries, sleep=self.sleep)
                if not isinstance(values, np.ndarray) or values.shape != (11, 260, 260):
                    raise ValueError('HLS provider output shape mismatch')
                target.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=target.parent, prefix='.hls-') as tmp:
                    stage = Path(tmp)/'ready'
                    stage.mkdir()
                    with rasterio.open(stage/name, 'w', driver='GTiff', width=260, height=260, count=11,
                                       dtype='float32', crs='EPSG:6933', transform=hls.transform(unit),
                                       nodata=float('nan'), compress='deflate', tiled=True) as dst:
                        dst.write(values.astype('float32'))
                        dst.descriptions = hls.LAYERS
                    stats = inspect(stage/name, unit)
                    write_json_exclusive(stage/'receipt.json', dict(item=item, sha256=checksum(stage/name), counts=stats, code=code_hashes()))
                    os.rename(stage, target)
            receipt = json.loads((target/'receipt.json').read_text())
            stats = inspect(target/name, unit)
            expected = dict(item=item, sha256=checksum(target/name), counts=stats, code=code_hashes())
            if receipt != expected:
                raise ValueError('HLS checkpoint corrupted')
            assets[name], counts[name] = receipt['sha256'], stats
        with tempfile.TemporaryDirectory(dir=root, prefix='.hls-') as tmp:
            stage = Path(tmp)/'ready'
            stage.mkdir()
            for item in records:
                name = item['id']+'.tif'
                os.link(root/'granules'/item['id']/name, stage/name)
            state, reason = availability(counts)
            meta = dict(hls.profile(unit), assets=assets, granules=records, valid_pixel_counts=counts,
                        state=state, reason=reason, processing_code_sha256=code_hashes())
            write_json_exclusive(stage/'manifest.json', meta)
            self.validate(self._prepared(unit, stage))
            os.rename(stage, annual)
        return self._prepared(unit, annual)

    def validate(self, prepared):
        key(prepared.unit)
        meta = json.loads(prepared.files[-1].read_text())
        if meta != prepared.public_metadata or any(meta.get(k) != v for k,v in hls.profile(prepared.unit).items()) or meta['processing_code_sha256'] != code_hashes():
            raise ValueError('HLS manifest identity mismatch')
        records = hls.checked_records(meta['granules'], prepared.unit)
        names = [r['id']+'.tif' for r in records]
        root = prepared.files[-1].parent
        if set(meta['assets']) != set(names) or {p.name for p in root.iterdir()} != set(names)|{'manifest.json'} or tuple(p.name for p in prepared.files) != tuple(meta['assets'])+('manifest.json',):
            raise ValueError('HLS file membership mismatch')
        counts = {}
        for name in names:
            if checksum(root/name) != meta['assets'][name]:
                raise ValueError('HLS checksum mismatch')
            counts[name] = inspect(root/name, prepared.unit)
        state, reason = availability(counts)
        if meta['valid_pixel_counts'] != counts or (meta['state'], meta['reason']) != (state, reason):
            raise ValueError('HLS availability mismatch')
        return ValidationResult(True, dict(integrity='passed', grid='passed', time='passed', quality_codes='passed'),
                                () if reason is None else (reason,))


def availability(counts):
    if not counts:
        return 'unavailable', 'no_provider_granules'
    n = sum(v[b] for v in counts.values() for b in hls.BANDS)
    if not n:
        return 'unavailable', 'no_eligible_reflectance'
    if n != len(counts)*len(hls.BANDS)*260*260:
        return 'partial', 'quality_exclusions_or_tile_coverage'
    return 'available', None
