from copy import deepcopy
from dataclasses import asdict
import unittest
from sm_benchmark_agent.grid import anchor_cell_from_id
from sm_benchmark_agent.gldas_workflow import same_anchor_metadata

class ContextIdentityTests(unittest.TestCase):
    def test_proj_inverse_roundoff_only_not_grid_change(self):
        expected=asdict(anchor_cell_from_id('EASE2_M09km_R0285_C3179'))
        actual=deepcopy(expected)
        actual['centre_latitude']+=7e-9
        self.assertTrue(same_anchor_metadata(actual,expected))
        actual['centre_latitude']+=1e-5
        self.assertFalse(same_anchor_metadata(actual,expected))
        actual=deepcopy(expected);actual['bounds']['xmin']+=0.001
        self.assertFalse(same_anchor_metadata(actual,expected))
        actual=deepcopy(expected);actual['centre_latitude']=float('nan')
        self.assertFalse(same_anchor_metadata(actual,expected))
