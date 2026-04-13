"""Observer classes for kivy_thor.reactive."""

import cython

from .internal import noop, default_error
from .disposable import SingleAssignmentDisposable, Disposable


@cython.cclass
class Observer:
    """Base observer that enforces terminal-message grammar.

    OnError and OnCompleted are terminal: after either fires, no further
    messages are delivered.
    """

    is_stopped: cython.bint
    _handler_on_next: object
    _handler_on_error: object
    _handler_on_completed: object

    def __init__(
        self,
        on_next: object = None,
        on_error: object = None,
        on_completed: object = None,
    ):
        self.is_stopped = False
        self._handler_on_next = on_next or noop
        self._handler_on_error = on_error or default_error
        self._handler_on_completed = on_completed or noop

    def on_next(self, value: object) -> None:
        if not self.is_stopped:
            self._on_next_core(value)

    @cython.ccall
    def _on_next_core(self, value: object) -> None:
        self._handler_on_next(value)

    def on_error(self, error: object) -> None:
        if not self.is_stopped:
            self.is_stopped = True
            self._on_error_core(error)

    @cython.ccall
    def _on_error_core(self, error: object) -> None:
        self._handler_on_error(error)

    def on_completed(self) -> None:
        if not self.is_stopped:
            self.is_stopped = True
            self._on_completed_core()

    @cython.ccall
    def _on_completed_core(self) -> None:
        self._handler_on_completed()

    def dispose(self) -> None:
        self.is_stopped = True

    @cython.ccall
    def fail(self, error: object) -> cython.bint:
        if not self.is_stopped:
            self.is_stopped = True
            self._on_error_core(error)
            return True
        return False

    def throw(self, error: Exception) -> None:
        raise error

    def as_observer(self):
        return Observer(self.on_next, self.on_error, self.on_completed)


@cython.cclass
class AutoDetachObserver:
    """Observer that auto-disposes on terminal events (error/completed)."""

    is_stopped: cython.bint
    _on_next: object
    _on_error: object
    _on_completed: object
    _subscription: SingleAssignmentDisposable

    def __init__(
        self,
        on_next: object = None,
        on_error: object = None,
        on_completed: object = None,
    ):
        self._on_next = on_next or noop
        self._on_error = on_error or default_error
        self._on_completed = on_completed or noop
        self._subscription = SingleAssignmentDisposable()
        self.is_stopped = False

    def on_next(self, value: object) -> None:
        if self.is_stopped:
            return
        self._on_next(value)

    def on_error(self, error: object) -> None:
        if self.is_stopped:
            return
        self.is_stopped = True
        try:
            self._on_error(error)
        finally:
            self.dispose()

    def on_completed(self) -> None:
        if self.is_stopped:
            return
        self.is_stopped = True
        try:
            self._on_completed()
        finally:
            self.dispose()

    def set_subscription(self, value: object) -> None:
        self._subscription.disposable = value

    subscription = property(fset=set_subscription)

    def dispose(self) -> None:
        self.is_stopped = True
        self._subscription.dispose()

    @cython.ccall
    def fail(self, error: object) -> cython.bint:
        if self.is_stopped:
            return False
        self.is_stopped = True
        self._on_error(error)
        return True
