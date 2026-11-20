"""Experimental frequency-A-only GCOV window reader with explicit budgets."""
from dataclasses import asdict
import math
from pathlib import Path
from .nisar_processing import POWER_TERMS, delivery_grid, reproject_layer
from .nisar_http import NISARRangeFS


def read_window(item, anchor_id, session, *, max_bytes=64*1024*1024, max_requests=128):
    import h5py
    import numpy as np
    from affine import Affine
    from pyproj import Transformer
    fs=NISARRangeFS(session,max_bytes=max_bytes,max_requests=max_requests)
    output={}; native_stats={}
    with fs.open(item['url']) as stream, h5py.File(stream,'r') as f:
        group=f['/science/LSAR/GCOV/grids/frequencyA']
        spacing=float(group['xCoordinateSpacing'][()]);dy=float(group['yCoordinateSpacing'][()])
        if spacing<=0 or not math.isclose(dy,-spacing,abs_tol=1e-6):raise ValueError('Unsupported native grid')
        grid=delivery_grid(anchor_id,spacing);epsg=int(group['projection'][()])
        box=(grid.bounds.xmin,grid.bounds.ymin,grid.bounds.xmax,grid.bounds.ymax)
        left,bottom,right,top=Transformer.from_crs(6933,epsg,always_xy=True).transform_bounds(*box,densify_pts=21)
        xs=group['xCoordinates'][:];ys=group['yCoordinates'][:]
        if not np.allclose(np.diff(xs),spacing) or not np.allclose(np.diff(ys),dy):raise ValueError('Irregular coordinate axes')
        cols=np.flatnonzero((xs>=left-2*spacing)&(xs<=right+2*spacing))
        rows=np.flatnonzero((ys>=bottom-2*spacing)&(ys<=top+2*spacing))
        if not len(rows) or not len(cols) or max(len(rows),len(cols))>2048:raise ValueError('Window empty or exceeds bound')
        selection=np.s_[rows[0]:rows[-1]+1,cols[0]:cols[-1]+1]
        transform=Affine(spacing,0,float(xs[cols[0]])-spacing/2,0,dy,float(ys[rows[0]])-dy/2)
        names=sorted(POWER_TERMS & set(group))
        if not names:raise ValueError('No supported real-valued power terms')
        names+=['mask','inputDataExceptionMask','numberOfLooks','rtcGammaToSigmaFactor']
        for name in names:
            ds=group[name]
            if ds.shape!=(len(ys),len(xs)):raise ValueError('Band grid mismatch')
            values=ds[selection];fill=ds.attrs.get('_FillValue')
            if fill is None:raise ValueError('Undeclared fill requires review')
            output[name],_=reproject_layer(values,name=name,source_transform=transform,
                source_crs=epsg,anchor_id=anchor_id,fill_value=fill)
            valid=np.isfinite(output[name]);native_stats[name]=dict(valid=int(valid.sum()),missing=int((~valid).sum()))
    meta=dict(schema='nisar-frequency-a-window-v1',anchor_id=anchor_id,granule_id=item['id'],time=item['time'],
        maturity=item['maturity'],collection=item['collection'],frequency='A',bands=names,
        native_spacing_m=spacing,native_epsg=epsg,target_grid=asdict(grid),statistics=native_stats,
        normalization='gamma0 linear power for covariance diagonal terms',
        missing='declared provider fill to NaN; valid zero power retained',
        quality_policy='provider QA codes preserved with nearest neighbor; no additional exclusion',
        auxiliary_policy='area-averaged looks/factor are descriptive; not effective looks or exact post-average sigma0 conversion',
        bytes_received=fs.bytes_received,requests=fs.requests)
    return output,meta


def write_window(output,meta,path):
    import numpy as np
    import rasterio
    from affine import Affine
    path=Path(path)
    if path.exists():raise FileExistsError(path)
    g=meta['target_grid'];path.parent.mkdir(parents=True,exist_ok=True)
    with rasterio.open(path,'w',driver='GTiff',count=len(meta['bands']),dtype='float32',
        width=g['columns'],height=g['rows'],crs='EPSG:6933',nodata=np.nan,
        transform=Affine(g['exact_spacing_m'],0,g['upper_left_x_m'],0,-g['exact_spacing_m'],g['upper_left_y_m']),
        compress='deflate',tiled=True) as dst:
        dst.write(np.stack([output[n] for n in meta['bands']]))
        dst.descriptions=tuple(meta['bands'])
