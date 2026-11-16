from pathlib import Path
import tempfile
import unittest
import numpy as np
import rasterio
from rasterio.io import MemoryFile
from affine import Affine
from pyproj import Transformer, CRS
from sm_benchmark_agent.grid import anchor_cell, context_grid, ContextResolution
from sm_benchmark_agent.processing.landcover import derive_landcover, NATIVE_CRS


class ProjectionTests(unittest.TestCase):
    def payload(self, values, crs, transform, nodata=255):
        with MemoryFile() as m:
            with m.open(driver='GTiff',height=values.shape[0],width=values.shape[1],count=1,
                        dtype='uint8',crs=crs,transform=transform,nodata=nodata) as w:
                w.write(values,1)
            return m.read()

    def run_derivation(self, payload, context):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'lc.tif'
            derive_landcover(payload,target,context,2020)
            with rasterio.open(target) as r:
                self.assertEqual(r.crs.to_epsg(),6933)
                self.assertEqual(r.shape,(26,26))
                return r.read(1)

    def test_realistic_mislabelled_native_grid_matches_independent_point_oracle(self):
        for lon,lat in [(-106,36),(10,52),(20,5)]:
            c=context_grid(anchor_cell(lon,lat),ContextResolution('500 m',2))
            tr=Transformer.from_crs(6933,NATIVE_CRS,always_xy=True)
            b=c.bounds
            left,bottom,right,top=tr.transform_bounds(b.xmin-2000,b.ymin-2000,b.xmax+2000,b.ymax+2000,densify_pts=41)
            s=463.3127165279165; ox=-20015109.354;oy=10007554.677003
            col=int(np.floor((left-ox)/s));row=int(np.floor((oy-top)/s))
            transform=Affine(s,0,ox+col*s,0,-s,oy-row*s)
            width=int(np.ceil((right-transform.c)/s))+2;height=int(np.ceil((transform.f-bottom)/s))+2
            yy,xx=np.indices((height,width));values=((yy+3*xx)%17+1).astype('uint8')
            bad=CRS.from_proj4('+proj=sinu +ellps=WGS84 +units=m').to_wkt()
            actual=self.run_derivation(self.payload(values,bad,transform),c)
            iy,ix=np.indices((26,26))
            x=c.upper_left_x_m+(ix+.5)*c.exact_spacing_m
            y=c.upper_left_y_m-(iy+.5)*c.exact_spacing_m
            sx,sy=tr.transform(x,y)
            expected=values[np.floor((transform.f-sy)/s).astype(int),np.floor((sx-transform.c)/s).astype(int)]
            np.testing.assert_array_equal(actual,expected)
            np.testing.assert_array_equal(actual,self.run_derivation(self.payload(values,NATIVE_CRS,transform),c))

    def test_masked_legal_class_is_not_resurrected(self):
        c=context_grid(anchor_cell(-106,36),ContextResolution('500 m',2))
        t=Affine(c.exact_spacing_m,0,c.upper_left_x_m,0,-c.exact_spacing_m,c.upper_left_y_m)
        actual=self.run_derivation(self.payload(np.full((26,26),5,dtype='uint8'),'EPSG:6933',t,nodata=5),c)
        self.assertTrue(np.all(actual==255))

    def test_wrong_extent_and_unknown_projection_fail_not_missing_data(self):
        c=context_grid(anchor_cell(-106,36),ContextResolution('500 m',2))
        for crs,t in [('EPSG:6933',Affine(500,0,0,0,-500,0)),('EPSG:4326',Affine(.01,0,-106,0,-.01,36))]:
            with self.assertRaises(ValueError):
                self.run_derivation(self.payload(np.ones((26,26),dtype='uint8'),crs,t),c)


if __name__=='__main__':unittest.main()
