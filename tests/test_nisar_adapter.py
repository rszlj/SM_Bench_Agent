import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from dataclasses import asdict
from sm_benchmark_agent.nisar_adapter import GCOVAdapter,PROFILE
from sm_benchmark_agent.nisar_processing import delivery_grid
from sm_benchmark_agent.adapters import SourceUnit
from sm_benchmark_agent.multi_workflow import plan_multi,execute_multi
from sm_benchmark_agent.archives import verify_archive
import test_multi_workflow

AID='EASE2_M09km_R0285_C3179'
class Provider:
    def __init__(self):self.calls=[];self.fail=True
    def discover(self,unit):
        return [dict(id=f'NISAR_L2_PR_GCOV_034_119_D_068_2005_DHDH_A_2026110{i}T110637_2026110{i}T110712_P05036_N_F_J_001',
            time=f'2026-11-0{i}T11:06:37+00:00',maturity='validated',collection='NISAR_L2_GCOV_V1',
            url=f'https://nisar.asf.earthdatacloud.nasa.gov/NISAR_L2_PR_GCOV_034_119_D_068_2005_DHDH_A_2026110{i}T110637_2026110{i}T110712_P05036_N_F_J_001.h5') for i in [1,5]]
    def fetch(self,unit,item):
        self.calls.append(item['time'])
        if self.fail and '11-05' in item['time']:raise ValueError('test interruption')
        g=delivery_grid(unit.anchor_id,20);names=['HHHH','mask','inputDataExceptionMask','numberOfLooks','rtcGammaToSigmaFactor']
        arrays={n:np.ones((650,650),dtype='float32') for n in names}
        meta=dict(anchor_id=unit.anchor_id,granule_id=item['id'],time=item['time'],maturity='validated',collection=item['collection'],frequency='A',
            native_spacing_m=20,target_grid=asdict(g),bands=names,statistics={n:dict(valid=422500,missing=0) for n in names})
        return arrays,meta

class AdapterTests(unittest.TestCase):
    def test_absent_a_and_prevalidated_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            unit=SourceUnit('nisar_gcov',PROFILE,AID,2026)
            provider=Provider();rows=provider.discover(unit)
            for row in rows:
                row['id']=row['id'].replace('_2005_','_0005_')
                row['url']=row['url'].replace('_2005_','_0005_')
            provider.discover=lambda u:rows
            adapter=GCOVAdapter(provider=provider)
            result=adapter.prepare(adapter.plan(unit,asset_root=tmp),output_root=tmp)
            self.assertEqual(result.public_metadata['state'],'unavailable')
            self.assertEqual(len(result.public_metadata['skipped_without_frequency_a']),2)
            self.assertFalse(provider.calls)
            old=SourceUnit('nisar_gcov',PROFILE,AID,2025)
            self.assertEqual(adapter.plan(old,asset_root=tmp).state,'unavailable')

    def test_resume_corruption_and_dates(self):
        with tempfile.TemporaryDirectory() as tmp,patch('socket.socket',side_effect=AssertionError('no network')):
            root=Path(tmp);unit=SourceUnit('nisar_gcov',PROFILE,AID,2026,'2026-11-01','2026-11-07');p=Provider();a=GCOVAdapter(provider=p)
            plan=a.plan(unit,asset_root=root)
            with self.assertRaises(RuntimeError):a.prepare(plan,output_root=root)
            p.fail=False;result=a.prepare(plan,output_root=root)
            self.assertEqual(p.calls.count('2026-11-01T11:06:37+00:00'),1)
            self.assertTrue(a.validate(result).passed);self.assertEqual(a.plan(unit,asset_root=root).state,'reusable')
            result.files[0].write_bytes(b'corrupt')
            with self.assertRaises(ValueError):a.validate(result)
    def test_unified_archive_and_cache_reuse(self):
        # Synthetic contexts, real adapter API; no provider network operations.
        harness=test_multi_workflow.MultiTests();harness.setUp()
        try:
            req,kwargs=harness.setup_scope(2026);req['sources']=['nisar_gcov'];req.pop('years');req.update(start='2026-11-01',end='2026-11-07')
            # Context plan is full-year; date-scoped context checks accept only matching periods.
            req.pop('start');req.pop('end');req['years']=[2026]
            p=Provider();p.fail=False;adapter=GCOVAdapter(provider=p);adapters={'nisar_gcov':adapter}
            plan=plan_multi(req,adapters=adapters,**kwargs);result=execute_multi(plan,accepted_plan_id=plan['plan_id'],adapters=adapters)
            verify_archive(result['archive']);new=plan_multi(req,adapters=adapters,**kwargs)
            self.assertEqual(execute_multi(new,accepted_plan_id=new['plan_id'],adapters=adapters)['status'],'reused')
        finally:harness.doCleanups()
