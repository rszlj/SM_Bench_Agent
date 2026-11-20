"""Validated GCOV frequency-A adapter; atomic scene checkpoints and annual assembly."""
from datetime import datetime, timezone
import json,os,re,tempfile,time
from pathlib import Path
from .adapters import PreparedSource,SourcePlan,ValidationResult
from .delivery import checksum
from .gldas21 import digest,write_json_exclusive,fetch_with_retry
from . import periods
from .nisar_processing import delivery_grid,POWER_TERMS,QA_TERMS
from .nisar_window import read_window,write_window
from .nisar_discovery import discover,COLLECTIONS

PROFILE='nisar-gcov-validated-a-20m-100m-v1'
MAX_SCENES=64
def scene_name(item):return 'gcov_'+digest(item['id'])[:20]+'.tif'

def code_hashes():
    root=Path(__file__).parent
    return {n:checksum(root/n) for n in ['nisar_adapter.py','nisar_discovery.py','nisar_processing.py','nisar_http.py','nisar_window.py','hls_http.py','grid.py','periods.py']}

def profile(unit):
    if unit.source_id!='nisar_gcov' or unit.profile_id!=PROFILE:raise ValueError('Invalid GCOV profile')
    periods.bounds(unit)
    delivery_grid(unit.anchor_id,20)
    return dict(source_id='nisar_gcov',profile_id=PROFILE,anchor_id=unit.anchor_id,year=unit.year,
        **periods.metadata(unit),collection=COLLECTIONS['validated'],maturity='validated',frequency='A',
        grid_policy='10/20 m -> nominal 20 m; 80 m -> nominal 100 m; identical context bounds',
        normalization='gamma0 linear power',quality_policy='provider flags retained; no extra screening',
        auxiliary_policy='averaged factor/looks descriptive only; not effective looks or exact sigma0 conversion',
        missing_values='declared fills to NaN; no imputation',extension_only=True)

def checked(records,unit):
    if not isinstance(records,list) or len(records)>MAX_SCENES:raise ValueError('GCOV scene bound exceeded')
    seen=set()
    for r in records:
        if set(r)!={'id','time','maturity','collection','url'} or not re.fullmatch(r'NISAR_[A-Za-z0-9_]+',r['id']) or r['id'] in seen:raise ValueError('Invalid GCOV discovery identity')
        tokens=r['id'].split('_')
        if len(tokens)<12 or tokens[1:4]!=['L2','PR','GCOV'] or not re.fullmatch(r'\d{4}',tokens[8]):raise ValueError('Unsupported GCOV acquisition')
        stamp=datetime.fromisoformat(r['time'])
        if stamp.utcoffset() is None or stamp.utcoffset().total_seconds()!=0 or not periods.contains(unit,stamp):raise ValueError('GCOV dates mismatch')
        if r['maturity']!='validated' or r['collection']!=COLLECTIONS['validated']:raise ValueError('Maturity mixing forbidden')
        from urllib.parse import urlsplit
        url=urlsplit(r['url'])
        if url.scheme!='https' or url.hostname!='nisar.asf.earthdatacloud.nasa.gov' or url.query or not url.path.endswith('/'+r['id']+'.h5'):raise ValueError('Invalid GCOV data URL')
        seen.add(r['id'])
    return sorted(records,key=lambda r:(r['time'],r['id']))

class EarthdataGCOV:
    def discover(self,unit):
        start,end=periods.bounds(unit)
        from datetime import timedelta
        return discover(unit.anchor_id,start.date().isoformat(),(end-timedelta(days=1)).date().isoformat(),limit=MAX_SCENES)['records']
    def fetch(self,unit,item):
        if not hasattr(self,'session'):
            import netrc,requests
            from .earthdata_setup import check_local
            if check_local()['status']!='configured':raise ValueError('Earthdata credentials require setup')
            auth=netrc.netrc(str(Path.home()/'.netrc')).authenticators('urs.earthdata.nasa.gov')
            self.session=requests.Session();self.session.auth=(auth[0],auth[2])
        return read_window(item,unit.anchor_id,self.session,max_bytes=96*1024*1024,max_requests=128)

def inspect(path,meta,unit):
    import numpy as np,rasterio
    from affine import Affine
    g=delivery_grid(unit.anchor_id,meta['native_spacing_m'])
    if meta['frequency']!='A' or meta['anchor_id']!=unit.anchor_id or meta['target_grid']!=__import__('dataclasses').asdict(g):raise ValueError('GCOV source/grid mismatch')
    names=meta['bands']
    if len(names)!=len(set(names)) or not set(names)&POWER_TERMS or set(names)-(POWER_TERMS|QA_TERMS|{'numberOfLooks','rtcGammaToSigmaFactor'}):raise ValueError('Invalid GCOV layers')
    with rasterio.open(path) as ds:
        transform=Affine(g.exact_spacing_m,0,g.upper_left_x_m,0,-g.exact_spacing_m,g.upper_left_y_m)
        if ds.crs.to_epsg()!=6933 or ds.shape!=(g.rows,g.columns) or ds.descriptions!=tuple(names) or not ds.transform.almost_equals(transform,precision=1e-6) or any(d!='float32' for d in ds.dtypes) or ds.nodata is None or not np.isnan(ds.nodata):raise ValueError('GCOV raster schema mismatch')
        stats={}
        for i,n in enumerate(names,1):
            a=ds.read(i);v=a[np.isfinite(a)]
            if np.isinf(a).any() or (n in POWER_TERMS and (v<0).any()) or (n in QA_TERMS and ((v<0)|(v!=np.floor(v))).any()):raise ValueError('Invalid GCOV values')
            stats[n]=dict(valid=len(v),missing=a.size-len(v))
    if stats!=meta['statistics']:raise ValueError('GCOV statistics mismatch')

class GCOVAdapter:
    source_id,profile_id='nisar_gcov',PROFILE
    def __init__(self,*,provider=None,retries=2,sleep=time.sleep):
        if retries!=2:raise ValueError('GCOV requires two bounded retries')
        self.provider,self.retries,self.sleep=provider,retries,sleep
    def key(self,unit):
        profile(unit);return f'{PROFILE}/{unit.anchor_id}/{unit.year}'+periods.suffix(unit)
    def _prepared(self,unit,root):
        meta=json.loads((root/'manifest.json').read_text())
        return PreparedSource(unit,tuple(root/n for n in meta['assets'])+(root/'manifest.json',),meta)
    def plan(self,unit,*,asset_root):
        key=self.key(unit);root=Path(asset_root)/key
        if (root/'annual').exists():
            self.validate(self._prepared(unit,root/'annual'));return SourcePlan(unit,'reusable','validated_cache',key,0,0)
        if periods.bounds(unit)[1]<=datetime(2026,10,21,tzinfo=timezone.utc):return SourcePlan(unit,'unavailable','outside_validated_collection_period',key,0,0)
        return SourcePlan(unit,'retrievable','frequency A only; <=64 scenes, <=96 MiB/128 ranges per scene attempt; incomplete date coverage retained',key,None,None)
    def prepare(self,plan,*,output_root,credential_ref=None):
        unit=plan.unit;root=Path(output_root)/self.key(unit)
        if plan.work_key!=self.key(unit):raise ValueError('GCOV work key mismatch')
        if (root/'annual').exists():
            output=self._prepared(unit,root/'annual');self.validate(output);return output
        if self.plan(unit,asset_root=output_root).state=='unavailable':raise ValueError('Outside validated period')
        root.mkdir(parents=True,exist_ok=True);provider=self.provider or EarthdataGCOV();discovery=root/'discovery.json'
        if not discovery.exists():
            records=checked(fetch_with_retry(lambda:provider.discover(unit),retries=2,sleep=self.sleep),unit)
            write_json_exclusive(discovery,dict(profile=profile(unit),code=code_hashes(),records=records,sha256=digest(records)))
        doc=json.loads(discovery.read_text());records=checked(doc['records'],unit)
        if doc!=dict(profile=profile(unit),code=code_hashes(),records=records,sha256=digest(records)):raise ValueError('GCOV discovery checkpoint changed')
        selected=[r for r in records if r['id'].split('_')[8][:2]!='00'];receipts={}
        for item in selected:
            name=scene_name(item);folder=root/'scenes'/name[:-4]
            if not folder.exists():
                values,meta=fetch_with_retry(lambda:provider.fetch(unit,item),retries=2,sleep=self.sleep)
                if meta['granule_id']!=item['id'] or meta['time']!=item['time'] or meta['maturity']!='validated' or meta['collection']!=COLLECTIONS['validated']:raise ValueError('GCOV fetched identity mismatch')
                folder.parent.mkdir(exist_ok=True)
                with tempfile.TemporaryDirectory(dir=folder.parent,prefix='.gcov-') as tmp:
                    stage=Path(tmp)/'ready';stage.mkdir();write_window(values,meta,stage/name);inspect(stage/name,meta,unit)
                    write_json_exclusive(stage/'receipt.json',dict(item=item,meta=meta,sha256=checksum(stage/name),code=code_hashes()))
                    os.rename(stage,folder)
            receipt=json.loads((folder/'receipt.json').read_text())
            if receipt['item']!=item or receipt['code']!=code_hashes() or checksum(folder/name)!=receipt['sha256']:raise ValueError('GCOV scene checkpoint corrupted')
            inspect(folder/name,receipt['meta'],unit);receipts[name]=receipt
        with tempfile.TemporaryDirectory(dir=root,prefix='.gcov-') as tmp:
            stage=Path(tmp)/'ready';stage.mkdir()
            for name,r in receipts.items():os.link(root/'scenes'/name[:-4]/name,stage/name)
            # Source availability never implies full-year or additional QA acceptance.
            state='partial' if receipts else 'unavailable';reason='provider_quality_flags_retained' if receipts else 'no_frequency_a_granules'
            public=[{k:v for k,v in r['meta'].items() if k not in ['bytes_received','requests']} for r in receipts.values()]
            meta=dict(profile(unit),assets={n:r['sha256'] for n,r in receipts.items()},granules=public,
                skipped_without_frequency_a=[r['id'] for r in records if r not in selected],state=state,reason=reason,processing_code_sha256=code_hashes())
            write_json_exclusive(stage/'manifest.json',meta);output=self._prepared(unit,stage);self.validate(output);os.rename(stage,root/'annual')
        return self._prepared(unit,root/'annual')
    def validate(self,prepared):
        unit=prepared.unit;meta=json.loads(prepared.files[-1].read_text());root=prepared.files[-1].parent
        if meta!=prepared.public_metadata or any(meta.get(k)!=v for k,v in profile(unit).items()) or meta['processing_code_sha256']!=code_hashes():raise ValueError('GCOV annual profile mismatch')
        if {p.name for p in root.iterdir()}!=set(meta['assets'])|{'manifest.json'} or tuple(p.name for p in prepared.files)!=tuple(meta['assets'])+('manifest.json',):raise ValueError('GCOV membership mismatch')
        if set(meta['assets'])!={scene_name({'id':r['granule_id']}) for r in meta['granules']}:raise ValueError('GCOV granule membership mismatch')
        for r in meta['granules']:
            stamp=datetime.fromisoformat(r['time'])
            if not periods.contains(unit,stamp):raise ValueError('GCOV annual dates mismatch')
            p=root/scene_name({'id':r['granule_id']})
            if checksum(p)!=meta['assets'][p.name]:raise ValueError('GCOV checksum mismatch')
            inspect(p,r,unit)
        expected=('partial','provider_quality_flags_retained') if meta['assets'] else ('unavailable','no_frequency_a_granules')
        if (meta['state'],meta['reason'])!=expected:raise ValueError('GCOV availability mismatch')
        return ValidationResult(True,dict(integrity='passed',grid='passed',dates='passed',frequency='A'),(meta['reason'],))
