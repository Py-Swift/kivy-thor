"""Notification classes for materialising observable events as objects."""

import cython


@cython.cclass
class Notification:
    """Wraps an observable event (next / error / completed) as a value.

    Useful for materialise/dematerialise operators.
    """

    kind: str
    value: object
    error: object

    def __init__(self, kind: str, value: object = None, error: object = None):
        self.kind = kind
        self.value = value
        self.error = error

    @staticmethod
    def create_on_next(value: object):
        return Notification("N", value=value)

    @staticmethod
    def create_on_error(error: object):
        return Notification("E", error=error)

    @staticmethod
    def create_on_completed():
        return Notification("C")

    def accept(self, on_next: object = None, on_error: object = None, on_completed: object = None) -> None:
        if self.kind == "N":
            if on_next is not None:
                on_next(self.value)
        elif self.kind == "E":
            if on_error is not None:
                on_error(self.error)
        elif self.kind == "C":
            if on_completed is not None:
                on_completed()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Notification):
            return NotImplemented
        o: Notification = other
        return self.kind == o.kind and self.value == o.value and self.error == o.error

    def __repr__(self) -> str:
        if self.kind == "N":
            return f"OnNext({self.value!r})"
        elif self.kind == "E":
            return f"OnError({self.error!r})"
        return "OnCompleted()"
