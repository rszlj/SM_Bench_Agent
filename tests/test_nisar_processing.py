import unittest
import numpy as np
from affine import Affine
from sm_benchmark_agent.nisar_processing import delivery_grid,reproject_layer

AID='EASE2_M09km_R0285_C3179'

class GridTests(unittest.TestCase):
    def test_unequal_area_weights_not_fixed_pixel_blocks(self):
        g=delivery_grid(AID,80)
        t=Affine(80,0,g.bounds.xmin,0,-80,g.bounds.ymax)
        n=170;data=np.tile((np.arange(n)%2)*10.,(n,1))
        out,_=reproject_layer(data,name='HHHH',source_transform=t,source_crs=6933,anchor_id=AID)
        width=g.exact_spacing_m
        expected=10*(width-80)/width
        self.assertAlmostEqual(float(out[0,0]),expected,places=5)
        self.assertNotAlmostEqual(float(out[0,0]),5,places=2)

    def test_two_grids_bounds_and_nesting(self):
        a=delivery_grid(AID,10);b=delivery_grid(AID,20);c=delivery_grid(AID,80)
        self.assertEqual(a,b);self.assertEqual(a.bounds,c.bounds)
        self.assertEqual((a.rows,c.rows),(650,130))
        self.assertAlmostEqual(c.exact_spacing_m,a.exact_spacing_m*5)
        with self.assertRaises(ValueError):delivery_grid(AID,40)

    def test_constant_power_zero_fill_and_discrete_codes(self):
        for spacing in (10,20,80):
            g=delivery_grid(AID,spacing)
            t=Affine(spacing,0,g.bounds.xmin-200,0,-spacing,g.bounds.ymax+200)
            n=int((g.bounds.xmax-g.bounds.xmin+400)/spacing)+2
            for name,value in [('HHHH',0),('HVHV',2),('mask',17)]:
                out,meta=reproject_layer(np.full((n,n),value),name=name,source_transform=t,
                    source_crs=6933,anchor_id=AID)
                self.assertEqual(out.shape,(g.rows,g.columns))
                np.testing.assert_allclose(out,value)
            out,_=reproject_layer(np.full((n,n),-9999),name='HHHH',source_transform=t,
                source_crs=6933,anchor_id=AID,fill_value=-9999)
            self.assertTrue(np.isnan(out).all())
