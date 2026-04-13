"""Internal helpers and exceptions for kivy_thor.reactive."""

import cython


def noop(*args: object, **kwargs: object) -> None:
    pass


def default_error(error: Exception) -> None:
    if isinstance(error, Exception):
        raise error
    raise Exception(error)


def default_comparer(x: object, y: object) -> bool:
    return x == y


def identity(x: object) -> object:
    return x


class NotSet:
    pass


class DisposedException(Exception):
    pass


class SequenceContainsNoElementsError(Exception):
    pass


class ArgumentOutOfRangeException(Exception):
    pass


class WouldBlockException(Exception):
    pass


@cython.cclass
class Struct:
    """Simple mutable container used to share state across closures."""
    value: object

    def __init__(self, value: object = None):
        self.value = value
