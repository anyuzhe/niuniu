import unittest
from scripts.research.retail_crowding_residual_v1 import load_spec, factor_configs


class RetailCrowdingResidualTests(unittest.TestCase):
    def test_frozen_controls_split_family_and_resolution(self):
        spec=load_spec()
        self.assertEqual([r["name"] for r in spec["controls"]],["MOM20","VolumeShock20","AmountShock20"])
        self.assertEqual(spec["projection"]["fit_through"],"2022-12-31")
        self.assertEqual(spec["projection"]["evaluation_start"],"2023-01-01")
        self.assertEqual(spec["horizons"],[1,3,5,10,20])
        self.assertLessEqual(1/(spec["inference"]["permutation"]["resamples"]+1),
                             spec["inference"]["permutation"]["alpha"]/5)
        cfg=factor_configs(spec,tuple(f"sh.60{i:04d}" for i in range(10)))
        self.assertEqual(set(cfg),{"candidate","MOM20","VolumeShock20","AmountShock20"})
        self.assertEqual(cfg["MOM20"].parameters,{"lookback":20})


if __name__=="__main__":unittest.main()
