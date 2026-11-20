import unittest
from sm_benchmark_agent.nisar_http import NISARRangeFS
from test_hls_http import Session, Response
URL='https://nisar.asf.earthdatacloud.nasa.gov/test.h5'

class RangeTests(unittest.TestCase):
    def test_byte_limit_and_truncation(self):
        import io
        fs=NISARRangeFS(Session(),max_bytes=2)
        with self.assertRaises(ValueError):fs.range(URL,0,3)
        s=Session()
        def truncated(*a,**k):
            response=Response(b'abcd',0,3);response.raw=io.BytesIO(b'ab');return response
        s.get=truncated
        with self.assertRaises(ConnectionError):NISARRangeFS(s).range(URL,0,3)

    def test_budget_and_untrusted_url(self):
        fs=NISARRangeFS(Session(),max_requests=1)
        self.assertEqual(len(fs.range(URL,0,3)[0]),4)
        with self.assertRaises(ValueError):fs.range(URL,0,3)
        with self.assertRaises(ValueError):NISARRangeFS(Session()).range('https://example.org/test.h5',0,3)

    def test_ignored_range_stops(self):
        s=Session();s.get=lambda *a,**k:Response(b'abc',0,0,status=200)
        with self.assertRaises(ValueError):NISARRangeFS(s).range(URL,0,0)
