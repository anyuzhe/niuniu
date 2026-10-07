#!/bin/bash
# one chunk of the delisted backfill: raw plan A and qfq plan B in parallel, each <=150s
export NIUNIU_DATA_ROOT=$HOME/niuniu-data-vm
cd $HOME/mnt/niuniu/scripts/collect
P=$HOME/niuniu-data-vm/lake/bronze/provider=baostock/_plans
timeout 168 python3 bars_delisted.py apply --plan $P/delisted-bars-e87a64d9197f.json --approve e87a64d9197f293975cde9f60a9597b092d446ba8c332e346c34e91569077645 --max-seconds 150 > $HOME/research/lowfreq/dl_A.log 2>&1 &
timeout 168 python3 bars_delisted.py apply --plan $P/delisted-bars-949be12811c2.json --approve 949be12811c225bca18766888f321c42b3d05b0dda6a27c07cd7a1e9f33b6b29 --max-seconds 150 > $HOME/research/lowfreq/dl_B.log 2>&1 &
wait
tail -2 $HOME/research/lowfreq/dl_A.log; tail -2 $HOME/research/lowfreq/dl_B.log
