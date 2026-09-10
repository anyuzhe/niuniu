"""Cooperative checkpoints for the existing in-process research queue."""
from contextlib import contextmanager
from contextvars import ContextVar

_callback=ContextVar('quantlab_progress',default=None)

class ResearchCancelled(Exception):
    pass

@contextmanager
def research_progress(callback):
    token=_callback.set(callback)
    try:yield
    finally:_callback.reset(token)

def checkpoint(stage=None,completed=None,total=None):
    callback=_callback.get()
    if callback is not None:callback(stage,completed,total)
