import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import h5py
import numpy as np
from sm_benchmark_agent.nisar_window import read_window
from sm_benchmark_agent.nisar_processing import delivery_grid

class WindowTests(unittest.TestCase):
    def fixture(self,path,spacing):
        grid=delivery_grid('EASE2_M09km_R0285_C3179',spacing)
        n=int((grid.bounds.xmax-grid.bounds.xmin)/spacing)+8
        with h5py.File(path,'w') as f:
            group=f.create_group('/science/LSAR/GCOV/grids/frequencyA')
            group['xCoordinateSpacing']=spacing;group['yCoordinateSpacing']=-spacing
            group['projection']=6933
            group['xCoordinates']=grid.bounds.xmin-3*spacing+np.arange(n)*spacing
            group['yCoordinates']=grid.bounds.ymax+3*spacing-np.arange(n)*spacing
            for name,value in [('HHHH',2),('mask',17),('inputDataExceptionMask',3),('numberOfLooks',4),('rtcGammaToSigmaFactor',.8)]:
                ds=group.create_dataset(name,data=np.full((n,n),value,dtype='float32'))
                ds.attrs['_FillValue']=-9999.
    def test_all_three_spacings_without_frequency_b(self):
        # Fixture has no frequencyB group: any attempt to read it fails.
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.h5'
            class LocalFS:
                bytes_received=0;requests=0
                def __init__(self,*a,**kw):pass
                def open(self,*a):return path.open('rb')
            for spacing,size in [(10,650),(20,650),(80,130)]:
                self.fixture(path,spacing)
                with patch('sm_benchmark_agent.nisar_window.NISARRangeFS',LocalFS):
                    arrays,meta=read_window(dict(url='unused',id='test',time='2026-11-01T00:00:00Z',maturity='validated',collection='test'),
                        'EASE2_M09km_R0285_C3179',None)
                self.assertEqual(meta['frequency'],'A');self.assertEqual(arrays['HHHH'].shape,(size,size))
                np.testing.assert_allclose(arrays['HHHH'],2)
                np.testing.assert_allclose(arrays['mask'],17)
