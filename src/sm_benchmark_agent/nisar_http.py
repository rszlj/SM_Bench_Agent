"""Budgeted NISAR HDF5 range transport; never falls back to whole-file download."""
import re
from urllib.parse import urlsplit
from .hls_http import RangeFS

class NISARRangeFS(RangeFS):
    def __init__(self, session, *, max_bytes=64*1024*1024, max_requests=128):
        if type(max_bytes) is not int or type(max_requests) is not int or max_bytes<1 or max_requests<1:
            raise ValueError('Positive integer transfer budgets required')
        super().__init__(session)
        self.max_bytes, self.max_requests = max_bytes, max_requests

    def range(self, url, start, end):
        p=urlsplit(url)
        if (p.scheme!='https' or p.hostname!='nisar.asf.earthdatacloud.nasa.gov'
                or p.query or not p.path.endswith('.h5')):
            raise ValueError('Untrusted NISAR data URL')
        if (start<0 or end<start or end-start+1>1024*1024
                or self.requests>=self.max_requests or self.bytes_received+end-start+1>self.max_bytes):
            raise ValueError('NISAR range budget exceeded')
        self.requests+=1
        with self.session.get(url,headers={'Range':f'bytes={start}-{end}',
                'Accept-Encoding':'identity'},stream=True,timeout=(20,40)) as response:
            response.raise_for_status()
            match=re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)',response.headers.get('Content-Range',''))
            if response.status_code!=206 or not match:
                raise ValueError('Provider ignored range; full download forbidden')
            first,last,total=map(int,match.groups())
            if first!=start or last!=min(end,total-1) or not 0<=first<=last<total:
                raise ValueError('Invalid range response')
            value=response.raw.read(last-first+2)
            self.bytes_received+=len(value)
            if len(value)!=last-first+1:
                raise ConnectionError('Truncated NISAR range')
            return value,total
