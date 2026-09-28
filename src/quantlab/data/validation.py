"""Source-independent validation of normalized bars."""

import polars as pl

SUSPENSION_INPUT_CONTRACT = "preserve_suspension_state_v2"
PUBLISHED_RESEARCH_CONTRACT = "published_qfq_status_research_only_v1"


def suspension_state_aware(bars: pl.DataFrame) -> bool:
    if "input_contract" not in bars.columns:
        return False
    if bars["input_contract"].null_count() or bars["input_contract"].n_unique() != 1 \
            or bars["input_contract"][0] not in (SUSPENSION_INPUT_CONTRACT, PUBLISHED_RESEARCH_CONTRACT):
        raise ValueError("Unsupported or mixed input_contract in normalized bars")
    if "bs_trade_status" not in bars.columns:
        raise ValueError("Suspension-state contract requires bs_trade_status")
    return True


def validate_bars(bars: pl.DataFrame) -> None:
    if bars.is_empty():
        raise ValueError("No bars in requested interval")
    structural = ["symbol", "datetime", "available_at"]
    prices = ["open", "high", "low", "close"]
    flow = ["volume", "turnover"]
    required = structural + prices + flow
    if any(column not in bars.columns for column in required):
        raise ValueError("Missing required bar field")
    if any(bars[c].null_count() for c in structural):
        raise ValueError("Null in structural bar field")
    if bars.select(pl.struct("symbol", "datetime").is_duplicated().any()).item():
        raise ValueError("Duplicate symbol/datetime")
    state_aware = suspension_state_aware(bars)
    published_research = state_aware and bars['input_contract'][0] == PUBLISHED_RESEARCH_CONTRACT
    if published_research:
        if 'timeframe' not in bars.columns or bars['timeframe'].null_count() or bars['timeframe'].unique().to_list() != ['1d']:
            raise ValueError('Published research contract requires daily bars')
        if 'bs_is_st' not in bars.columns or bars['bs_is_st'].null_count() or bars.filter(~pl.col('bs_is_st').is_in([0,1])).height:
            raise ValueError('Published research requires explicit retrospective ST status')
        if 'adj_factor' not in bars.columns or bars['adj_factor'].null_count() or bars.filter(~pl.col('adj_factor').is_finite() | (pl.col('adj_factor')<=0)).height:
            raise ValueError('Published research requires valid source qfq factor')
        if 'vendor_previous_close' in bars.columns:
            raise ValueError('Published research must not fabricate vendor_previous_close')
    if state_aware:
        if bars["bs_trade_status"].null_count() or bars.filter(~pl.col("bs_trade_status").is_in([0, 1])).height:
            raise ValueError("State-aware bars require explicit bs_trade_status 0/1")
        tradable = bars.filter(pl.col("bs_trade_status") == 1)
        suspended = bars.filter(pl.col("bs_trade_status") == 0)
        if any(tradable[c].null_count() for c in prices + flow):
            raise ValueError("Tradable rows require complete OHLCV")
        invalid = tradable.filter(
            pl.any_horizontal([~pl.col(c).is_finite() for c in prices + flow])
            | (pl.min_horizontal(*prices) <= 0)
            | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
            | (pl.col("volume") < 0) | (pl.col("turnover") < 0)
        )
        if invalid.height:
            raise ValueError(f"Invalid tradable OHLCV in {invalid.height} bars")
        if suspended.height:
            if suspended.filter(pl.any_horizontal([pl.col(c).is_not_null() for c in prices])).height:
                raise ValueError("Suspended rows must not synthesize OHLC fill prices")
            for column in flow:
                if suspended.filter(pl.col(column).is_not_null() & (~pl.col(column).is_finite() | (pl.col(column) < 0))).height:
                    raise ValueError("Suspended volume/turnover must be null or finite nonnegative source values")
            if published_research:
                if suspended.filter(pl.any_horizontal([pl.col(c).is_not_null() & (pl.col(c)!=0) for c in flow])).height:
                    raise ValueError('Published suspended rows must retain null/zero source activity')
            elif "vendor_previous_close" not in bars.columns or suspended["vendor_previous_close"].null_count() \
                    or suspended.filter(~pl.col("vendor_previous_close").is_finite() | (pl.col("vendor_previous_close") <= 0)).height:
                raise ValueError("Suspended rows require a finite positive vendor_previous_close valuation mark")
    else:
        if any(bars[c].null_count() for c in prices + flow):
            raise ValueError("Null in required bar field")
        invalid = bars.filter(
            pl.any_horizontal([~pl.col(c).is_finite() for c in prices + flow])
            | (pl.min_horizontal(*prices) <= 0)
            | (pl.col("high") < pl.max_horizontal("open", "low", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "high", "close"))
            | (pl.col("volume") < 0) | (pl.col("turnover") < 0)
        )
        if invalid.height:
            raise ValueError(f"Invalid OHLCV in {invalid.height} bars")
    if bars.filter(pl.col("available_at") < pl.col("datetime")).height:
        raise ValueError("Bar available before datetime")


def ordered_bars(bars: pl.DataFrame, *, for_execution: bool = False, virtual_qfq: bool = False) -> pl.DataFrame:
    validate_bars(bars)
    if type(virtual_qfq) is not bool or virtual_qfq and not for_execution:
        raise ValueError('virtual_qfq is an explicit simulation-only consumer')
    published='input_contract' in bars.columns and bars['input_contract'][0] == PUBLISHED_RESEARCH_CONTRACT
    if virtual_qfq:
        if not published:raise ValueError('virtual_qfq requires the exact published qfq/status input contract')
        first=bars.sort('symbol','datetime').group_by('symbol',maintain_order=True).first()
        if first['close'].null_count():raise ValueError('virtual_qfq requires an observed first close for every security')
    elif for_execution and published:
        raise ValueError('Published qfq/status research-only input has no account valuation contract; execution is forbidden')
    if bars["timeframe"].n_unique() != 1:
        raise ValueError("Detect one timeframe at a time")
    ordered = bars.sort("symbol", "datetime")
    if ordered.filter(pl.col("available_at").diff().over("symbol") < pl.duration()).height:
        raise ValueError("Bar availability must be nondecreasing")
    return ordered


