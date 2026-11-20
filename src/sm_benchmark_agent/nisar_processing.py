"""GCOV two-grid reprojection primitives; no implicit quality-code interpretation."""
from dataclasses import asdict
import math
from .grid import anchor_cell_from_id, context_grid, ContextResolution

POWER_TERMS = {'HHHH', 'HVHV', 'VVVV', 'VHVH', 'RHRH', 'RVRV'}
QA_TERMS = {'mask', 'inputDataExceptionMask'}
CONTINUOUS = POWER_TERMS | {'numberOfLooks', 'rtcGammaToSigmaFactor'}


def delivery_grid(anchor_id, native_spacing):
    spacing = abs(float(native_spacing))
    if any(math.isclose(spacing, n, abs_tol=1e-6, rel_tol=0) for n in (10,20)):
        resolution = ContextResolution('20 m', 50)
    elif math.isclose(spacing, 80, abs_tol=1e-6, rel_tol=0):
        resolution = ContextResolution('100 m', 10)
    else:
        raise ValueError('Unsupported GCOV native spacing')
    return context_grid(anchor_cell_from_id(anchor_id), resolution)


def reproject_layer(values, *, name, source_transform, source_crs, anchor_id,
                    fill_value=None):
    """Keep gamma0 linear; QA uses nearest, continuous fields area averaging.

    Auxiliary averages are descriptive resampled fields, not effective looks or
    a factor guaranteed to convert an averaged gamma0 into averaged sigma0.
    No sigma0 is constructed here. Provider fill and negative power are missing;
    zero power is valid. Provider QA codes are retained, not silently screened.
    """
    import numpy as np
    from affine import Affine
    from rasterio.warp import reproject, Resampling
    if name not in CONTINUOUS | QA_TERMS:
        raise ValueError('Unreviewed GCOV layer')
    if (source_transform.b != 0 or source_transform.d != 0 or source_transform.a <= 0
            or source_transform.e >= 0 or not math.isclose(source_transform.a,-source_transform.e,abs_tol=1e-6)):
        raise ValueError('Expected north-up square native grid')
    grid = delivery_grid(anchor_id, source_transform.a)
    data = np.asarray(values)
    if data.ndim != 2 or not 0 < min(data.shape) <= max(data.shape) <= 2048 or np.iscomplexobj(data):
        raise ValueError('Invalid native GCOV window')
    valid = np.isfinite(data)
    if fill_value is not None:
        valid &= data != fill_value
    if name in POWER_TERMS:
        valid &= data >= 0
    if name in QA_TERMS and ((data[valid] < 0) | (data[valid] != np.floor(data[valid]))).any():
        raise ValueError('Invalid quality codes')
    source = np.where(valid,data,np.nan).astype('float32')
    target = np.full((grid.rows, grid.columns),np.nan,dtype='float32')
    affine = Affine(grid.exact_spacing_m,0,grid.upper_left_x_m,0,-grid.exact_spacing_m,grid.upper_left_y_m)
    reproject(source,target,src_transform=source_transform,src_crs=source_crs,
        src_nodata=np.nan,dst_transform=affine,dst_crs='EPSG:6933',dst_nodata=np.nan,
        resampling=Resampling.nearest if name in QA_TERMS else Resampling.average)
    return target, dict(grid=asdict(grid),native_spacing_m=source_transform.a,
        resampling='nearest' if name in QA_TERMS else 'area_weighted_average',
        missing='NaN',quality_policy='provider codes retained; no additional screening',
        normalization='gamma0_linear_power' if name in POWER_TERMS else 'auxiliary')
