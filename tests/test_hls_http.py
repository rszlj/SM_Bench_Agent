import io
import unittest
from sm_benchmark_agent.hls_http import RangeFS,BLOCK

URL='https://data.lpdaac.earthdatacloud.nasa.gov/lp-prod-protected/example.tif'

class Response:
    def __init__(self,data,start,end,status=206):
        self.status_code=status
        self.headers={'Content-Range':f'bytes {start}-{end}/{len(data)}'}
        self.raw=io.BytesIO(data[start:end+1])
    def __enter__(self):return self
    def __exit__(self,*a):pass
    def raise_for_status(self):pass

class Session:
    def __init__(self):self.data=bytes(range(256))*(BLOCK//128);self.calls=0
    def get(self,url,headers,**kwargs):
        self.calls+=1
        start,end=map(int,headers['Range'][6:].split('-'))
        return Response(self.data,start,min(end,len(self.data)-1))

class HTTPTests(unittest.TestCase):
    def test_seek_cross_block_cached_reads_and_eof(self):
        session=Session();fs=RangeFS(session)
        with fs.open(URL) as f:
            f.seek(BLOCK-3)
            self.assertEqual(f.read(10),session.data[BLOCK-3:BLOCK+7])
            self.assertEqual(session.calls,3)
            f.seek(5);self.assertEqual(f.read(3),session.data[5:8])
            self.assertEqual(session.calls,3)
            f.seek(-2,2);self.assertEqual(f.read(10),session.data[-2:])
            self.assertEqual(f.read(1),b'')

    def test_no_full_tile_fallback_or_untrusted_host(self):
        session=Session()
        session.get=lambda *a,**kw:Response(b'abc',0,0,status=200)
        with self.assertRaisesRegex(ValueError,'fallback'):
            RangeFS(session).open(URL)
        with self.assertRaises(FileNotFoundError):
            RangeFS(session).open('https://example.com/file.tif')

    def test_truncated_range_rejected(self):
        session=Session()
        r=Response(b'abcdef',0,3);r.raw=io.BytesIO(b'ab')
        session.get=lambda *a,**kw:r
        with self.assertRaises(ConnectionError):
            RangeFS(session).range(URL,0,3)
