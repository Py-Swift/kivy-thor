"""Functional composition helpers for kivy_thor.reactive."""

from functools import reduce
from typing import Any


def compose(*operators):
    """Compose multiple operators left to right.

    Examples:
        >>> compose()(source) == source
        >>> compose(f)(source) == f(source)
        >>> compose(f, g)(source) == g(f(source))
    """

    def _compose(source: Any) -> Any:
        return reduce(lambda obs, op: op(obs), operators, source)

    return _compose


def pipe(__value: Any, *fns) -> Any:
    """Pipe a value through a sequence of functions left to right.

    Examples:
        >>> pipe(x, fn) == fn(x)
        >>> pipe(x, fn, gn) == gn(fn(x))
    """
    return compose(*fns)(__value)
