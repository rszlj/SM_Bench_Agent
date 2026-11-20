import io
import json
import unittest
from sm_benchmark_agent.nisar_discovery import discover

class DiscoveryTests(unittest.TestCase):
    def run_query(self, entries, **kw):
        def opener(url, timeout):
            self.assertIn('NISAR_L2_GCOV_V1', url)
            return io.BytesIO(json.dumps({'feed': {'entry': entries}}).encode())
        return discover('EASE2_M09km_R0285_C3179', '2026-11-01', '2026-11-07', opener=opener, **kw)

    def entry(self):
        return dict(title='NISAR_TEST_GCOV',time_start='2026-11-02T01:00:00Z',links=[dict(
            rel='http://esipfed.org/ns/fedsearch/1.1/data#',
            href='https://nisar.asf.earthdatacloud.nasa.gov/test.h5')])

    def test_empty_and_explicit_collection(self):
        self.assertEqual(self.run_query([])['records'], [])
        self.assertEqual(self.run_query([self.entry()])['records'][0]['maturity'], 'validated')

    def test_untrusted_duplicate_and_limit_fail(self):
        e=self.entry(); e['links'][0]['href']='https://example.org/test.h5'
        with self.assertRaises(ValueError): self.run_query([e])
        with self.assertRaises(ValueError): self.run_query([self.entry()]*2)
        with self.assertRaises(ValueError): self.run_query([self.entry()]*2,limit=1)

    def test_half_open_dates(self):
        e=self.entry(); e['time_start']='2026-11-08T00:00:00Z'
        self.assertEqual(self.run_query([e])['records'], [])
