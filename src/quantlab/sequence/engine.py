from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import groupby

from quantlab.domain import Event, SequenceMatch, information_time, Timeframe
from quantlab.storage.codec import digest


@dataclass(frozen=True)
class EventSelector:
    factor_id: str
    version: str = "1.0.0"
    direction: int | None = None

    def __post_init__(self):
        if not isinstance(self.factor_id, str) or not self.factor_id or not isinstance(self.version, str) or not self.version:
            raise ValueError("Event selector requires id and version")
        if self.direction is not None and (type(self.direction) is not int or self.direction not in (-1, 0, 1)):
            raise ValueError("Invalid event direction")

    def matches(self, event: Event) -> bool:
        return event.factor_id == self.factor_id and event.version == self.version and (self.direction is None or event.direction == self.direction)


@dataclass(frozen=True)
class SequenceScope:
    start: int
    end: int
    timeout: timedelta
    invalidators: tuple[EventSelector, ...] = ()

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or not 0<=self.start<self.end:
            raise ValueError('Scope requires ordered step indices')
        if not isinstance(self.timeout,timedelta) or self.timeout<=timedelta(0):raise ValueError('Scope timeout must be positive')
        if not isinstance(self.invalidators,tuple) or not all(isinstance(v,EventSelector) for v in self.invalidators):raise ValueError('Scope invalidators require immutable selectors')


@dataclass(frozen=True)
class SequenceDefinition:
    sequence_id: str
    steps: tuple[EventSelector, ...]
    max_gap: timedelta
    invalidators: tuple[EventSelector, ...] = ()
    version: str = "1.0.0"
    optional_steps: tuple[int, ...] = ()
    scopes: tuple[SequenceScope, ...] = ()
    step_timeframes: tuple[Timeframe, ...] = ()

    def __post_init__(self):
        if not isinstance(self.scopes,tuple) or any(not isinstance(s,SequenceScope) or s.end>=len(self.steps) for s in self.scopes):raise ValueError('Invalid sequence scopes')
        if self.step_timeframes and (not isinstance(self.step_timeframes,tuple) or len(self.step_timeframes)!=len(self.steps) or any(not isinstance(t,Timeframe) for t in self.step_timeframes)):
            raise ValueError('Specify an explicit timeframe for every step')
        if (not isinstance(self.optional_steps,tuple) or len(set(self.optional_steps))!=len(self.optional_steps)
            or any(type(i) is not int or not 0<i<len(self.steps)-1 for i in self.optional_steps)):
            raise ValueError("Optional steps must be unique interior indices")
        if not isinstance(self.steps, tuple) or not isinstance(self.invalidators, tuple) or not all(
            isinstance(selector, EventSelector) for selector in (*self.steps, *self.invalidators)
        ):
            raise ValueError("Sequence selectors must be immutable tuples of EventSelector")
        if not self.sequence_id or not self.version or len(self.steps) < 2:
            raise ValueError("Sequence requires id, version and at least two steps")
        if not isinstance(self.max_gap, timedelta) or self.max_gap <= timedelta(0):
            raise ValueError("max_gap must be a positive timedelta")


class OrderedSequenceEngine:
    """One active instance per symbol/timeframe, without overlapping starts.

    Time window is half-open: next.available_at < last.available_at + max_gap.
    A call consumes complete timestamp groups through as_of; subsequent calls
    cannot add new events at or before that watermark. Exact replay is a no-op.
    """

    def __init__(self, definition: SequenceDefinition):
        self.definition = definition
        self._active: dict[tuple, tuple[Event, ...]] = {}
        self._positions: dict[tuple, int] = {}
        self._scope_clocks: dict[tuple, dict[int, datetime]] = {}
        self._seen: dict[str, str] = {}
        self._as_of: datetime | None = None

    def _record(self, events, status, available_at, invalidating_event_id=None):
        first = events[0]
        identity = {"sequence_id": self.definition.sequence_id, "version": self.definition.version,
            "steps": self.definition.steps, "max_gap_seconds": self.definition.max_gap.total_seconds(),
            "invalidators": self.definition.invalidators, "first_event_id": first.event_id,
            "symbol": first.symbol, "timeframe": first.timeframe}
        if self.definition.optional_steps:identity["optional_steps"]=self.definition.optional_steps
        if self.definition.scopes:identity['scopes']=[{'start':s.start,'end':s.end,'timeout_seconds':s.timeout.total_seconds(),'invalidators':s.invalidators} for s in self.definition.scopes]
        if self.definition.step_timeframes:identity['step_timeframes']=self.definition.step_timeframes
        return SequenceMatch(self.definition.sequence_id, self.definition.version, first.symbol,
            tuple(e.event_id for e in events), first.occurred_at, available_at, status,
            digest(identity), first.timeframe, invalidating_event_id)

    def _expire(self, at):
        records = []
        for key, events in list(self._active.items()):
            deadline = events[-1].available_at + self.definition.max_gap
            for index,start in self._scope_clocks.get(key,{}).items():
                deadline=min(deadline,start+self.definition.scopes[index].timeout)
            if deadline <= at:
                records.append(self._record(events, "timeout", deadline))
                del self._active[key]
                self._positions.pop(key,None)
                self._scope_clocks.pop(key,None)
        return records

    def advance(self, events: Sequence[Event], as_of: datetime) -> list[SequenceMatch]:
        information_time(as_of, as_of)
        if self._as_of is not None and as_of < self._as_of:
            raise ValueError("Sequence clock cannot move backwards")
        # Validate the entire batch before changing state.
        pending, fingerprints = {}, {}
        for event in events:
            fingerprint = digest(event)
            old = self._seen.get(event.event_id, fingerprints.get(event.event_id))
            if old is not None:
                if fingerprint != old:
                    raise ValueError("Conflicting payload for event id")
                continue
            if event.available_at > as_of:
                raise ValueError("Future event is not available yet")
            if self._as_of is not None and event.available_at <= self._as_of:
                raise ValueError("Late event at or before sequence watermark")
            # Verify that time arithmetic will not fail after mutating state.
            event.available_at + self.definition.max_gap
            for scope in self.definition.scopes:event.available_at+scope.timeout
            fingerprints[event.event_id] = fingerprint
            pending[event.event_id] = deepcopy(event)
        ordered = sorted(pending.values(), key=lambda e: (e.available_at, e.symbol, e.timeframe.value, e.event_id))
        result = []
        for at, group in groupby(ordered, key=lambda e: e.available_at):
            result.extend(self._expire(at))
            by_key = {}
            for event in group:
                by_key.setdefault((event.symbol, self.definition.step_timeframes[0] if self.definition.step_timeframes else event.timeframe), []).append(event)
            for key, candidates in by_key.items():
                matched = self._active.get(key, ())
                invalidators=(*self.definition.invalidators,*[s for i in self._scope_clocks.get(key,{}) for s in self.definition.scopes[i].invalidators])
                invalid = next((event for event in candidates if any(s.matches(event) for s in invalidators)), None)
                if invalid is not None:
                    if matched:
                        result.append(self._record(matched, "invalidated", at, invalid.event_id))
                        del self._active[key]
                        self._positions.pop(key,None)
                        self._scope_clocks.pop(key,None)
                    continue
                position = self._positions.get(key,0)
                event = None
                while position < len(self.definition.steps):
                    expected = self.definition.steps[position]
                    event = next((e for e in candidates if expected.matches(e) and (not self.definition.step_timeframes or e.timeframe==self.definition.step_timeframes[position])), None)
                    if event is not None or position not in self.definition.optional_steps:break
                    position += 1
                if event is None:
                    continue
                matched = (*matched, event)
                clocks=self._scope_clocks.setdefault(key,{})
                for i,scope in enumerate(self.definition.scopes):
                    if scope.start<=position<scope.end:clocks.setdefault(i,at)
                    elif position>=scope.end:clocks.pop(i,None)
                complete = position+1 == len(self.definition.steps)
                result.append(self._record(matched, "completed" if complete else "active", at))
                if complete:
                    self._active.pop(key,None)
                    self._positions.pop(key,None)
                    self._scope_clocks.pop(key,None)
                else:
                    self._active[key] = matched
                    self._positions[key] = position+1
        result.extend(self._expire(as_of))
        self._seen.update(fingerprints)
        self._as_of = as_of
        return sorted(result, key=lambda r: (r.available_at, r.symbol, r.timeframe.value, r.match_id))
