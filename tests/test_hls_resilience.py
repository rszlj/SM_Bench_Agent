import io,unittest
import requests
from sm_benchmark_agent.hls_resilience import ResilientRangeFS,failure_kind
from test_hls_http import Session,Response,URL

class RetryTests(unittest.TestCase):
    def test_registry_uses_resilient_transport(self):
        from sm_benchmark_agent.adapters import default_registry
        from sm_benchmark_agent.hls_resilience import ResilientEarthdataHLS
        registry = default_registry()
        self.assertIsInstance(registry.require('hls_s30').provider, ResilientEarthdataHLS)

    def test_truncated_then_complete(self):
        s=Session(); original=s.get; calls=[]; waits=[]
        def get(*args,**kw):
            calls.append(kw['headers']['Range'])
            if len(calls)==1:
                r=Response(s.data,0,3);r.raw=io.BytesIO(b'ab');return r
            return original(*args,**kw)
        s.get=get;fs=ResilientRangeFS(s,sleep=waits.append)
        self.assertEqual(fs.range(URL,0,3)[0],s.data[:4])
        self.assertEqual(calls,['bytes=0-3','bytes=0-3'])
        self.assertEqual(waits,[5]);self.assertIsNone(fs.last_failure)

    def test_transient_exhaustion_bounded(self):
        s=Session();count=[];wait=[]
        def get(*a,**kw):count.append(1);raise requests.Timeout()
        s.get=get;fs=ResilientRangeFS(s,retries=2,sleep=wait.append)
        with self.assertRaises(requests.Timeout):fs.range(URL,0,0)
        self.assertEqual(len(count),3);self.assertEqual(wait,[5,10])
        self.assertEqual(fs.last_failure['kind'],'transient')

    def test_auth_quota_and_invalid_ranges_stop(self):
        for code in (401,403,429,404):
            s=Session();count=[]
            response=requests.Response();response.status_code=code
            def get(*a,**kw):count.append(1);raise requests.HTTPError(response=response)
            s.get=get
            with self.assertRaises(requests.HTTPError):ResilientRangeFS(s,sleep=lambda _:self.fail()).range(URL,0,0)
            self.assertEqual(len(count),1)
        self.assertEqual(failure_kind(ValueError('bad grid')),'review_required')
        s=Session();s.get=lambda *a,**kw:Response(b'abc',0,0,status=200)
        with self.assertRaises(ValueError):ResilientRangeFS(s,sleep=lambda _:self.fail()).range(URL,0,0)

if __name__=='__main__':unittest.main()
