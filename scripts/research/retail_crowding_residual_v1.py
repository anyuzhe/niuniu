#!/usr/bin/env python3
"""Frozen held-out residual test for Retail Crowding V1.

Host-only research. No model call, network download, registration promotion or trading.
"""
import argparse
import json
from datetime import date
from pathlib import Path
import sys

REPO_ROOT=Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0,str(REPO_ROOT))

import polars as pl

from quantlab.app import default_registry
from quantlab.data.base import DataRequest
from quantlab.data.universe import UniverseConfig, build_universe
from quantlab.domain import Timeframe
from quantlab.experiments.config import ExperimentConfig
from quantlab.experiments.runner import ExperimentRunner
from quantlab.statistics.permutation import PermutationConfig, holm
from quantlab.statistics.residual import residual_alpha
from quantlab.storage.codec import digest, encode
from quantlab.storage.experiments import LocalExperimentStore
from scripts.research.retail_crowding_v1 import (
    NullableQfqResearchProvider, QuantityAwareResearchUniverse, load_spec as load_v1_spec,
    select_symbols,
)

SPEC_PATH=REPO_ROOT/"docs/reference/retail-crowding-v1.1-residual.json"
V1_PATH=REPO_ROOT/"docs/reference/retail-crowding-v1.0.1.json"


def load_spec(path=SPEC_PATH):
    value=json.loads(Path(path).read_text())
    if value.get("spec_id")!="retail-crowding-v1-residual" or value.get("version")!="1.0.0":
        raise ValueError("Residual spec identity mismatch")
    horizons=value.get("horizons")
    if horizons != [1,3,5,10,20] or value["inference"]["holm_family_size"] != len(horizons):
        raise ValueError("Residual family must retain all five frozen horizons")
    cfg=PermutationConfig(**value["inference"]["permutation"])
    minimum_p=1/(cfg.resamples+1)
    first_holm=cfg.alpha/len(horizons)
    if minimum_p>first_holm:
        raise ValueError("Permutation resolution cannot reach first residual Holm threshold")
    if value["projection"]["fit_through"]!="2022-12-31" or value["projection"]["evaluation_start"]!="2023-01-01":
        raise ValueError("Residual split changed")
    return value


def factor_configs(spec, symbols):
    d=spec["data"]
    request=DataRequest(tuple(symbols),Timeframe.DAILY,date.fromisoformat(d["start"]),date.fromisoformat(d["end"]))
    refs=[("candidate",spec["candidate"])]+[(row["name"],row) for row in spec["controls"]]
    return {name:ExperimentConfig(
        research_question="Retail Crowding residual source · "+name,
        data=request,factor_id=ref["factor_id"],factor_version=ref["factor_version"],
        parameters=ref["parameters"],horizons=tuple(spec["horizons"]),quantiles=10,
        random_seed=20260928,replay=False,
    ) for name,ref in refs}


def execute(data_root:Path,output:Path,spec_path:Path=SPEC_PATH):
    spec=load_spec(spec_path)
    v1=load_v1_spec(V1_PATH)
    symbols,selection=select_symbols(data_root,v1,spec["selection"]["sample_per_board"])
    if selection["symbols_sha256"]!=spec["selection"]["expected_symbols_sha256"]:
        raise ValueError("Residual study symbol sample differs from frozen V1.0.1 sample")
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    (output/"spec.json").write_text(encode(spec))
    (output/"selection.json").write_text(encode({**selection,"symbols":symbols}))
    data=NullableQfqResearchProvider(Path(data_root),symbols)
    base=build_universe(Path(data_root),symbols,UniverseConfig(
        mode="listing",min_listed_days=spec["data"]["min_listed_days"]))
    runner=ExperimentRunner(data,default_registry(),QuantityAwareResearchUniverse(base),
                            LocalExperimentStore(output/"source-runs"))
    sources={}
    for name,cfg in factor_configs(spec,symbols).items():
        result=runner.run(cfg)
        sources[name]={"run_id":result.run_id,"artifact_path":str(result.artifact_path),
                       "experiment_id":result.experiment_id}
    identities={}
    for name,info in sources.items():
        record=json.loads((Path(info["artifact_path"])/"experiment.json").read_text())
        manifest=record["manifest"]
        identities[name]={"data_snapshot":manifest["data_snapshot"],"universe":manifest["universe"]}
    first=identities["candidate"]
    if any(value!=first for value in identities.values()):
        raise ValueError("Residual source factors do not share the exact data snapshot and universe")
    frames={name:pl.read_parquet(Path(info["artifact_path"])/"observations.parquet") for name,info in sources.items()}
    candidate=frames["candidate"]
    controls=[frames[row["name"]] for row in spec["controls"]]
    permutation=PermutationConfig(**spec["inference"]["permutation"])
    train_end=date.fromisoformat(spec["projection"]["fit_through"])
    tests=[];residual_paths={};projection_diagnostics=None
    for horizon in spec["horizons"]:
        seed=int(digest({"spec":spec,"horizon":horizon}),16)
        residual,summary=residual_alpha(candidate,controls,train_end,horizon,permutation=permutation,seed=seed)
        path=output/f"residual-h{horizon}.parquet";residual.write_parquet(path);residual_paths[str(horizon)]=str(path)
        if projection_diagnostics is None:
            projection_diagnostics={}
            for phase in ("train","test"):
                sample=residual.filter(pl.col("phase")==phase)
                candidate_var=sample["candidate"].var(ddof=0)
                residual_var=sample["value"].var(ddof=0)
                projection_diagnostics[phase]={
                    "rows":sample.height,
                    "candidate_variance":candidate_var,
                    "residual_variance":residual_var,
                    "linear_explained_fraction":None if not candidate_var else 1-residual_var/candidate_var,
                    "candidate_residual_correlation":sample.select(pl.corr("candidate","value")).item(),
                }
        tests.append({"horizon":horizon,"summary":summary,"p_value":summary["test"]["p_value"]})
    adjusted=holm([row["p_value"] for row in tests])
    for row,p in zip(tests,adjusted):
        estimate=row["summary"]["test_residual_ic"]
        row.update(p_holm=p,reject_holm=p is not None and p<=permutation.alpha,
                   expected_direction_matches=estimate is not None and estimate<0,
                   significant_expected_direction=bool(p is not None and p<=permutation.alpha and estimate is not None and estimate<0))
    record={
        "format":"niuniu-retail-crowding-residual-v1",
        "spec":spec,"selection":selection,"sources":sources,"source_identity":first,
        "projection_diagnostics":projection_diagnostics,"residual_paths":residual_paths,
        "tests":tests,
        "family":{"method":"holm_fwer","alpha":permutation.alpha,"planned_tests":len(tests),
                  "available_tests":sum(row["p_value"] is not None for row in tests)},
        "limitations":spec["limitations"],
    }
    record["checksum"]=digest(record)
    (output/"result.json").write_text(encode(record))
    lines=["# Retail Crowding V1 held-out residual study","",
           "Controls: MOM20 + VolumeShock20 + AmountShock20. Projection fitted through 2022-12-31; only 2023+ residual IC is tested.","",
           "| Horizon | Raw IC | Residual IC | raw p | Holm p | negative + significant |",
           "|---:|---:|---:|---:|---:|---|"]
    for row in tests:
        s=row["summary"]
        lines.append(f"| {row['horizon']} | {s['test_raw_ic']:.6g} | {s['test_residual_ic']:.6g} | {row['p_value'] if row['p_value'] is not None else 'N/A'} | {row['p_holm'] if row['p_holm'] is not None else 'N/A'} | {'yes' if row['significant_expected_direction'] else 'no'} |")
    lines+=["",
            f"Training linear explained fraction: {projection_diagnostics['train']['linear_explained_fraction']:.6f}.",
            f"Held-out linear explained fraction: {projection_diagnostics['test']['linear_explained_fraction']:.6f}.",
            "",*["- "+x for x in spec["limitations"]]]
    (output/"report.md").write_text("\n".join(lines)+"\n")
    return record


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument("--data-root",type=Path,required=True);p.add_argument("--output",type=Path,required=True);p.add_argument("--spec",type=Path,default=SPEC_PATH)
    a=p.parse_args(argv);result=execute(a.data_root,a.output,a.spec)
    print(encode({"ok":True,"output":str(a.output.resolve()),"family":result["family"],
                  "tests":[{k:r[k] for k in ("horizon","p_value","p_holm","reject_holm","expected_direction_matches","significant_expected_direction")} | {"raw_ic":r["summary"]["test_raw_ic"],"residual_ic":r["summary"]["test_residual_ic"]} for r in result["tests"]]}))


if __name__=="__main__":main()
