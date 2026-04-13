"""Type aliases for kivy_thor.reactive.

These are plain Python type aliases used for documentation and type checking.
Cython ignores them at the C level; .pyi stubs provide generics for IDEs.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TypeVar

_T = TypeVar("_T")
_T1 = TypeVar("_T1")
_T2 = TypeVar("_T2")
_TState = TypeVar("_TState")

# Observer callbacks
OnNext = Callable[[_T], None]
OnError = Callable[[Exception], None]
OnCompleted = Callable[[], None]

# Mapper / predicate
Mapper = Callable[[_T1], _T2]
MapperIndexed = Callable[[_T1, int], _T2]
Predicate = Callable[[_T1], bool]
PredicateIndexed = Callable[[_T1, int], bool]
Comparer = Callable[[_T1, _T1], bool]
SubComparer = Callable[[_T1, _T1], int]
Accumulator = Callable[[_TState, _T1], _TState]

# Scheduler
AbsoluteTime = datetime | float
RelativeTime = timedelta | float
AbsoluteOrRelativeTime = datetime | timedelta | float
ScheduledAction = Callable  # (scheduler, state | None) -> DisposableBase | None
ScheduledPeriodicAction = Callable  # (state) -> state

# Subscription function: (observer, scheduler | None) -> disposable
Subscription = Callable

# General
Action = Callable[[], None]
