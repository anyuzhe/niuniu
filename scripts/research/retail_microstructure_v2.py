#!/usr/bin/env python3
"""Build research-only daily TDX retail microstructure proxies and coverage evidence."""
import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SPEC_PATH=ROOT/"docs/reference/retail-microstructure-v2.0.2.json"
if str(ROOT) not in sys.path:
    sys.path.insert(0,str(ROOT))

from quantlab.data.retail_microstructure import RetailMicrostructureConfig,TdxRetailMicrostructure
from quantlab.storage.codec import encode


def parse_day(value):
    return date.fromisoformat(value) if value else None


def main(argv=None):
    p=argparse.ArgumentParser()
    p.add_argument("--data-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--start")
    p.add_argument("--end")
    a=p.parse_args(argv)
    out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    spec=json.loads(SPEC_PATH.read_text())
    if spec.get("spec_id")!="retail-microstructure-v2" or spec.get("version")!="0.2.0":
        raise ValueError("Retail Microstructure V2 current spec identity mismatch")
    config=RetailMicrostructureConfig()
    service=TdxRetailMicrostructure(a.data_root,config)
    coverage=service.coverage(parse_day(a.start),parse_day(a.end))
    features=service.daily_features(parse_day(a.start),parse_day(a.end))
    path=out/"features.parquet"
    features.write_parquet(path)
    manifest={
        "format":"niuniu-retail-microstructure-v2-preview",
        "spec":{"path":"docs/reference/retail-microstructure-v2.0.2.json","version":spec["version"],
                "sha256":hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()},
        "config":asdict(config),
        "coverage":coverage,
        "feature_rows":features.height,
        "feature_symbols":features["code"].n_unique() if features.height else 0,
        "feature_dates":features["date"].n_unique() if features.height else 0,
        "features_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
        "inference_performed":False,
        "limitations":[
            "notional_proxy is price times provider lots, not certified RMB",
            "small-order is a within-symbol-day average-lots-per-order bottom-quantile proxy",
            "TDX qualification remains personal research and not PIT"
        ],
    }
    (out/"manifest.json").write_text(encode(manifest))
    print(encode({
        "ok":True,
        "status":coverage["status"],
        "qualified_days":coverage["qualified_days"],
        "required_days":coverage["min_qualified_days"],
        "feature_rows":features.height,
        "output":str(out),
    }))


if __name__=="__main__":
    main()
