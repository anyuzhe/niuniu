"""Rebuild the three panic gates / pools for any panic window W (return window; std window stays 60), aligned to the c70 panel. Research only."""
import numpy as np, pandas as pd
import lib70 as L
Z = np.load('c72/series.npz'); nd = L.nd
cn = np.load('c72/codes_new.npy'); c70 = np.load('c70/codes.npy'); ix = {c: i for i, c in enumerate(cn)}; cols = np.array([ix[c] for c in c70])
mret = Z['mret'][:nd]; Ri = Z['Ri'][:nd]; Rq = Z['Rq'][:nd]
l1 = Z['l1'][cols]; lab = Z['lab'][:nd][:, cols]; uni = Z['uni'][:nd][:, cols]; poolA0 = Z['poolA'][:nd][:, cols]
TH = -1.5
def mkt_z(W):
    idx = np.cumprod(1 + mret); mk = np.full(nd, np.nan); mk[W:] = idx[W:] / idx[:-W] - 1
    sd = np.full(nd, np.nan); win = np.lib.stride_tricks.sliding_window_view(mret, 60); sd[59:] = win.std(axis=1, ddof=1)
    with np.errstate(invalid='ignore', divide='ignore'): return mk / (sd * np.sqrt(W))
def grp_z(R, W):
    z = np.full(R.shape, np.nan)
    for g in range(R.shape[1]):
        s = pd.Series(R[:, g]); c = np.exp(np.log1p(s).rolling(W, min_periods=W).sum()) - 1; sd = s.rolling(60, min_periods=40).std()
        with np.errstate(invalid='ignore', divide='ignore'): z[:, g] = (c / (sd * np.sqrt(W))).to_numpy()
    return z
def rW(W):
    C = L.C; a = np.full(C.shape, np.nan, np.float32); a[W:] = np.asarray(C[W:], np.float32) / np.asarray(C[:-W], np.float32) - 1; return a
def build(W, th=None):
    th = TH if th is None else th
    r = rW(W); fin = np.isfinite(r)
    zA = mkt_z(W); gA = np.isfinite(zA) & (zA <= th)
    zi = grp_z(Ri, W); ti = np.isfinite(zi) & (zi <= th); gB = ti.any(1)
    inT = np.zeros(uni.shape, bool); m = np.nonzero(l1 >= 0)[0]; inT[:, m] = ti[:, l1[m]]; pB = uni & inT & fin
    zq = grp_z(Rq, W); tq = np.isfinite(zq) & (zq <= th); gC = tq.any(1)
    inQ = np.zeros(uni.shape, bool)
    for k in range(5): inQ |= (lab == k) & tq[:, k:k + 1]
    pC = uni & inQ & fin
    return dict(gate={'A': gA, 'B': gB[:, None] & np.ones((1, 1), bool) if False else gB, 'C': gC}, pool={'A': poolA0, 'B': pB, 'C': pC}, rank=r, zA=zA)
def install(W, th=None):
    b = build(W, th)
    L.GATE = {s: np.broadcast_to(b['gate'][s][:, None], (nd, 1)) if False else b['gate'][s] for s in 'ACB'}; L.POOL = b['pool']; L._cache.clear()
    return b

def match_th(W, target_C):
    """threshold (grid step .05) making the amount-quintile gate days closest to target_C."""
    zq = grp_z(Rq, W); best = None
    for th in np.arange(-0.8, -3.01, -0.05):
        n = int((np.isfinite(zq) & (zq <= th)).any(1).sum())
        if best is None or abs(n - target_C) < best[0]: best = (abs(n - target_C), float(th))
    return best[1]
