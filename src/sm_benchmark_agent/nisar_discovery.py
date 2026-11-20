"""Bounded metadata-only NISAR GCOV discovery; no implicit maturity mixing."""
import argparse
from datetime import datetime
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from . import periods
from .adapters import SourceUnit
from .grid import anchor_cell_from_id, context_grid, ContextResolution
from .processing.srtm import _expanded_wgs84_bounds

COLLECTIONS = {
    'validated': 'NISAR_L2_GCOV_V1',
    'provisional': 'NISAR_L2_GCOV_PROVISIONAL_V1',
    'beta': 'NISAR_L2_GCOV_BETA_V1',
}


def parse_entries(entries, unit, maturity):
    if maturity not in COLLECTIONS:
        raise ValueError('Select one explicit maturity')
    records = []
    seen = set()
    for entry in entries:
        name = entry['title']
        if 'GCOV' not in name or not re.fullmatch(r'NISAR_[A-Za-z0-9_]+',name) or name in seen:
            raise ValueError('Unexpected or duplicate GCOV identity')
        stamp = datetime.fromisoformat(entry['time_start'].replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Missing UTC acquisition timezone')
        if not periods.contains(unit, stamp):
            continue
        links = []
        for link in entry.get('links', []):
            url = link.get('href', '')
            parsed = urlsplit(url)
            if (link.get('rel', '').endswith('/data#') and not link.get('inherited')
                    and parsed.scheme == 'https' and not parsed.query
                    and parsed.hostname and parsed.hostname.endswith('.earthdatacloud.nasa.gov')
                    and parsed.path.endswith('.h5')):
                links.append(url)
        if len(set(links)) != 1:
            raise ValueError('Expected one unsigned Earthdata Cloud HDF5 data link')
        seen.add(name)
        records.append(dict(id=name, time=stamp.isoformat(), maturity=maturity,
                            collection=COLLECTIONS[maturity], url=links[0]))
    return sorted(records, key=lambda r: (r['time'], r['id']))


def discover(anchor_id, start, end, *, maturity='validated', limit=16, opener=urlopen):
    if maturity not in COLLECTIONS or type(limit) is not int or not 1 <= limit <= 128:
        raise ValueError('Explicit maturity and limit 1..128 required')
    unit = SourceUnit('nisar_gcov', 'discovery-only-v1', anchor_id,
                      int(start[:4]), start, end)
    begin, stop = periods.bounds(unit)
    grid = context_grid(anchor_cell_from_id(anchor_id), ContextResolution('50 m', 20))
    box = _expanded_wgs84_bounds(grid, 0)
    if box[2] - box[0] > 180:
        raise ValueError('Antimeridian requires a separately reviewed route')
    query = urlencode(dict(short_name=COLLECTIONS[maturity], version='1',
        bounding_box=','.join(map(str, box)), temporal=f'{begin.isoformat()},{stop.isoformat()}',
        page_size=limit+1))
    with opener('https://cmr.earthdata.nasa.gov/search/granules.json?' + query, timeout=60) as response:
        payload = response.read(8*1024*1024+1)
    if len(payload) > 8*1024*1024:
        raise ValueError('CMR response exceeds bound')
    entries = json.loads(payload)['feed']['entry']
    if len(entries) > limit:
        raise ValueError('Granule limit exceeded; narrow dates before retrieval')
    return dict(schema='nisar-gcov-discovery-v1', anchor_id=anchor_id,
        start=start, end=end, maturity=maturity, collection=COLLECTIONS[maturity],
        records=parse_entries(entries, unit, maturity),
        status='metadata_only; raster retrieval not yet validated')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--anchor-id', required=True)
    p.add_argument('--start', required=True)
    p.add_argument('--end', required=True)
    p.add_argument('--maturity', choices=COLLECTIONS, default='validated')
    p.add_argument('--limit', type=int, default=16)
    a = p.parse_args()
    print(json.dumps(discover(a.anchor_id, a.start, a.end, maturity=a.maturity, limit=a.limit), indent=2))


if __name__ == '__main__':
    main()
