"""Observable – the core push-based stream type."""

import threading
from typing import Any

import cython

from .disposable import Disposable
from .observer import AutoDetachObserver, Observer
from .pipe import pipe as _pipe, compose as _compose


@cython.cclass
class Observable:
    """Observable sequence – push-based collection.

    Supports both functional (pipe-based) and fluent (method chaining)
    composition styles.

    Examples:
        >>> from kivy_thor.reactive import Observable
        >>> obs = Observable(lambda observer, scheduler: (
        ...     observer.on_next(1), observer.on_next(2), observer.on_completed()
        ... ))
        >>> obs.subscribe(on_next=print)
    """

    lock: object
    _subscribe_fn: object

    def __init__(self, subscribe: object = None):
        self.lock = threading.RLock()
        self._subscribe_fn = subscribe

    @cython.ccall
    def _subscribe_core(self, observer: object, scheduler: object = None) -> object:
        if self._subscribe_fn is not None:
            return self._subscribe_fn(observer, scheduler)
        return Disposable()

    def subscribe(
        self,
        on_next: object = None,
        on_error: object = None,
        on_completed: object = None,
        *,
        observer: object = None,
        scheduler: object = None,
    ) -> object:
        """Subscribe to the observable sequence.

        Accepts either an observer object or individual callbacks.

        Args:
            on_next: Action for each element, or an observer object.
            on_error: Action on error.
            on_completed: Action on completion.
            observer: An observer object (alternative to callbacks).
            scheduler: Default scheduler for this subscription.

        Returns:
            Disposable representing the subscription.
        """
        # If on_next is actually an observer-like object
        if on_next is not None and hasattr(on_next, "on_next") and callable(on_next.on_next):
            observer = on_next
            on_next = None

        if observer is not None:
            _on_next = observer.on_next
            _on_error = observer.on_error
            _on_completed = observer.on_completed
        else:
            _on_next = on_next
            _on_error = on_error
            _on_completed = on_completed

        auto_observer = AutoDetachObserver(_on_next, _on_error, _on_completed)

        def fix_subscriber(subscriber: object) -> object:
            if subscriber is not None and hasattr(subscriber, "dispose"):
                return subscriber
            if callable(subscriber):
                return Disposable(subscriber)
            return Disposable()

        def set_disposable(_scheduler: object = None, _state: object = None) -> None:
            try:
                subscriber = self._subscribe_core(auto_observer, scheduler)
            except Exception as ex:
                if not auto_observer.fail(ex):
                    raise
            else:
                auto_observer.subscription = fix_subscriber(subscriber)

        # Use CurrentThreadScheduler trampoline if available, otherwise direct call
        set_disposable()

        return Disposable(auto_observer.dispose)

    def pipe(self, *operators: object) -> Any:
        """Compose operators left to right and apply to this observable.

        Examples:
            >>> source.pipe() == source
            >>> source.pipe(f) == f(source)
            >>> source.pipe(g, f) == f(g(source))
        """
        return _pipe(self, *operators)

    def run(self, scheduler: object = None) -> Any:
        """Subscribe and block until the sequence completes.

        Returns the last emitted value, or raises if an error occurred.
        """
        from .internal import SequenceContainsNoElementsError

        has_value = [False]
        last_value = [None]
        error = [None]
        done = threading.Event()

        def on_next(value: object) -> None:
            has_value[0] = True
            last_value[0] = value

        def on_error(e: object) -> None:
            error[0] = e
            done.set()

        def on_completed() -> None:
            done.set()

        self.subscribe(on_next=on_next, on_error=on_error, on_completed=on_completed, scheduler=scheduler)
        done.wait()

        if error[0] is not None:
            raise error[0]
        if not has_value[0]:
            raise SequenceContainsNoElementsError()
        return last_value[0]

    def __add__(self, other: object):
        """Pythonic concat: zs = xs + ys."""
        from .observable import Observable  # self-reference is fine

        def subscribe(observer: object, scheduler: object = None) -> object:
            from .disposable import SerialDisposable
            subscription = SerialDisposable()

            def on_completed() -> None:
                subscription.disposable = other.subscribe(
                    observer, scheduler=scheduler
                )

            subscription.disposable = self.subscribe(
                on_next=observer.on_next,
                on_error=observer.on_error,
                on_completed=on_completed,
                scheduler=scheduler,
            )
            return subscription

        return Observable(subscribe)

    def __getitem__(self, key: object):
        """Slice support: source[1:10], source[1:-2:2]."""
        if isinstance(key, slice):
            start, stop, step = key.start, key.stop, key.step
        elif isinstance(key, int):
            start, stop, step = key, key + 1, 1
        else:
            raise TypeError(f"indices must be integers or slices, not {type(key).__name__}")

        from .operators._filter import slice_ as _slice
        return _slice(start, stop, step)(self)
