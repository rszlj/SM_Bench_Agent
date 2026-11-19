import json
import io
from pathlib import Path
import tempfile
import os
import types
import unittest
from unittest.mock import patch

import numpy as np
from affine import Affine

from sm_benchmark_agent import hls, periods
from sm_benchmark_agent.hls_adapter import HLSAdapter
from sm_benchmark_agent.adapters import SourceUnit


def unit():
    return SourceUnit('hls_s30', hls.PROFILE, 'EASE2_M09km_R0169_C1995', 2020,
                      '2020-06-01', '2020-06-07')


class Provider:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def discover(self, u):
        from datetime import timedelta
        start, end = periods.bounds(u)
        return [{'id': 'HLS.S30.T31UET.'+d.strftime('%Y%jT%H%M%S')+'.v2.0', 'time': d.isoformat()}
                for d in (start, start+timedelta(hours=1)) if d < end]

    def fetch(self, u, item):
        self.calls.append(item['id'])
        if len(self.calls) == self.fail:
            raise RuntimeError('simulated interruption')
        arrays = {b: np.full((260,260), 2000, dtype='int16') for b in hls.BANDS}
        arrays['Fmask'] = np.zeros((260,260), dtype='uint8')
        return hls.process(arrays, hls.transform(u), 'EPSG:6933', u)


class HLSTests(unittest.TestCase):
    def test_provider_native_windows_and_auth_binding(self):
        import rasterio
        from rasterio.warp import transform_bounds
        from rasterio.transform import from_origin
        u = unit()
        g = hls.grid(u)
        left, bottom, right, top = transform_bounds('EPSG:6933','EPSG:32632',
            g.upper_left_x_m,g.upper_left_y_m-260*g.exact_spacing_m,
            g.upper_left_x_m+260*g.exact_spacing_m,g.upper_left_y_m,densify_pts=21)
        original_open = rasterio.open
        previous = os.environ.get('NETRC')
        def login(**kwargs):
            self.assertEqual(kwargs, {'strategy':'netrc','persist':False})
            self.assertEqual(os.environ['NETRC'],str(Path.home()/'.netrc'))
            return types.SimpleNamespace(authenticated=True)
        fs = types.SimpleNamespace(client_kwargs={}, kwargs={}, open=lambda *a, **kw: None)
        fake = types.SimpleNamespace(login=login,get_requests_https_session=lambda:None)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for band in hls.LAYERS:
                with original_open(root/(band+'.tif'),'w',driver='GTiff',width=700,height=700,count=1,
                                   dtype='int16',crs='EPSG:32632',transform=from_origin(left-90,top+90,30,30),
                                   nodata=255 if band=='Fmask' else -9999) as dst:
                    dst.write(np.full((700,700),0 if band=='Fmask' else 2000,dtype='int16'),1)
            def local_open(url, **kwargs):
                self.assertTrue(url.startswith('https://data.lpdaac.earthdatacloud.nasa.gov/'))
                self.assertEqual(kwargs['opener'],fs.open)
                return original_open(root/(url.split('.')[-2]+'.tif'))
            with patch.dict('sys.modules',earthaccess=fake), patch('sm_benchmark_agent.hls_http.RangeFS',return_value=fs), patch('rasterio.open',side_effect=local_open), \
                 patch('sm_benchmark_agent.earthdata_setup.check_local',return_value={'status':'configured'}):
                result=hls.EarthdataHLS().fetch(u,Provider().discover(u)[0])
            np.testing.assert_allclose(result[:10],.2)
            np.testing.assert_array_equal(result[-1],0)
        self.assertEqual(os.environ.get('NETRC'),previous)

    def test_real_cmr_shape_uses_title_and_actual_start_not_filename_time(self):
        entry = {'producer_granule_id':'HLS.S30.T32ULD.2020153T103629',
                 'title':'HLS.S30.T32ULD.2020153T103629.v2.0',
                 'time_start':'2020-06-01T10:46:23.199Z'}
        with patch('sm_benchmark_agent.hls.urlopen', return_value=io.BytesIO(json.dumps({'feed':{'entry':[entry]}}).encode())):
            records = hls.EarthdataHLS().discover(unit())
        self.assertEqual(records[0]['id'], entry['title'])
        self.assertEqual(records[0]['time'], '2020-06-01T10:46:23.199000+00:00')

    def test_masks_before_average_and_preserves_negative_and_qa(self):
        u = unit()
        arrays = {b: np.full((520,520), 2000, dtype='int16') for b in hls.BANDS}
        qa = np.zeros((520,520), dtype='uint8')
        arrays['Fmask'] = qa
        # Three invalid pixels must not dilute one valid .2 pixel.
        qa[0,0] = 2
        qa[0,1] = 4
        qa[1,0] = 8
        for b in hls.BANDS:
            arrays[b][0:2, 2:4] = -1000
            arrays[b][0:2, 4:6] = -9999
            arrays[b][0:2, 6:8] = 12000
        qa[0:2, 8:10] = 192
        qa[0:2, 10:12] = 16
        qa[0:2, 12:14] = 32  # water remains eligible
        qa[0:2, 14:16] = 255
        result = hls.process(arrays, hls.transform(u)*Affine.scale(.5), 'EPSG:6933', u)
        np.testing.assert_allclose(result[:10,0,0], .2)
        np.testing.assert_allclose(result[:10,0,1], -.1)
        self.assertTrue(np.isnan(result[:10,0,2:6]).all())
        np.testing.assert_allclose(result[:10,0,6], .2)
        self.assertEqual(result[-1,0,6], 32)
        self.assertTrue(np.isnan(result[:,0,7]).all())

    def test_offline_plan_exact_dates_resume_and_integrity(self):
        u = unit()
        with tempfile.TemporaryDirectory() as tmp, patch('socket.socket', side_effect=AssertionError('No network')):
            root = Path(tmp)/'cache'
            provider = Provider(fail=2)
            adapter = HLSAdapter(provider=provider)
            plan = adapter.plan(u, asset_root=root)
            self.assertFalse(root.exists())
            self.assertIsNone(plan.remote_operations)
            with self.assertRaises(RuntimeError):
                adapter.prepare(plan, output_root=root)
            provider.fail = None
            prepared = adapter.prepare(plan, output_root=root)
            self.assertEqual(len(provider.calls), 3)
            self.assertTrue(adapter.validate(prepared).passed)
            self.assertEqual(adapter.plan(u, asset_root=root).state, 'reusable')
            self.assertEqual(len(adapter.prepare(plan, output_root=root).files), 3)
            prepared.files[0].write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                adapter.validate(prepared)

    def test_identity_scope_no_granules_and_all_cloud(self):
        u = unit()
        records = Provider().discover(u)
        with self.assertRaises(ValueError):
            hls.checked_records(records+records, u)
        records[0]['time'] = '2020-05-31T00:00:00+00:00'
        with self.assertRaises(ValueError):
            hls.checked_records(records, u)
        with tempfile.TemporaryDirectory() as tmp:
            for empty in (True, False):
                p = Provider()
                if empty:
                    p.discover = lambda u: []
                else:
                    p.fetch = lambda u, i: np.full((11,260,260), np.nan, dtype='float32')
                a = HLSAdapter(provider=p)
                root = Path(tmp)/str(empty)
                prepared = a.prepare(a.plan(u,asset_root=root), output_root=root)
                self.assertTrue(a.validate(prepared).passed)
                self.assertEqual(prepared.public_metadata['state'], 'unavailable')
                self.assertEqual(prepared.public_metadata['reason'], 'no_provider_granules' if empty else 'no_eligible_reflectance')


if __name__ == '__main__':
    unittest.main()
