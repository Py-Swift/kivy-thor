"""Disposable resources for kivy_thor.reactive."""

from threading import RLock

import cython

from .internal import noop


@cython.cclass
class Disposable:
    """Main disposable class. Invokes an action on first dispose call."""

    is_disposed: cython.bint
    action: object
    lock: object

    def __init__(self, action: object = None):
        self.is_disposed = False
        self.action = action or noop
        self.lock = RLock()

    def dispose(self) -> None:
        dispose = False
        with self.lock:
            if not self.is_disposed:
                dispose = True
                self.is_disposed = True
        if dispose:
            self.action()

    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.dispose()


@cython.cclass
class SingleAssignmentDisposable:
    """Disposable that allows a single assignment of its underlying disposable.

    Setting the disposable a second time raises an exception.
    """

    is_disposed: cython.bint
    current: object
    lock: object

    def __init__(self):
        self.is_disposed = False
        self.current = None
        self.lock = RLock()

    def get_disposable(self) -> object:
        return self.current

    def set_disposable(self, value: object) -> None:
        if self.current is not None:
            raise Exception("Disposable has already been assigned")

        should_dispose: cython.bint = False
        with self.lock:
            should_dispose = self.is_disposed
            if not should_dispose:
                self.current = value

        if self.is_disposed and value is not None:
            value.dispose()

    disposable = property(get_disposable, set_disposable)

    def dispose(self) -> None:
        old: object = None
        with self.lock:
            if not self.is_disposed:
                self.is_disposed = True
                old = self.current
                self.current = None
        if old is not None:
            old.dispose()


@cython.cclass
class SerialDisposable:
    """Disposable whose underlying resource can be swapped.

    Assigning a new disposable automatically disposes the previous one.
    """

    is_disposed: cython.bint
    current: object
    lock: object

    def __init__(self):
        self.is_disposed = False
        self.current = None
        self.lock = RLock()

    def get_disposable(self) -> object:
        return self.current

    def set_disposable(self, value: object) -> None:
        old: object = None
        should_dispose: cython.bint = False
        with self.lock:
            should_dispose = self.is_disposed
            if not should_dispose:
                old = self.current
                self.current = value

        if old is not None:
            old.dispose()
        if should_dispose:
            value.dispose()

    disposable = property(get_disposable, set_disposable)

    def dispose(self) -> None:
        old: object = None
        with self.lock:
            if not self.is_disposed:
                self.is_disposed = True
                old = self.current
                self.current = None
        if old is not None:
            old.dispose()


@cython.cclass
class CompositeDisposable:
    """A group of disposable resources that are disposed together."""

    is_disposed: cython.bint
    disposables: list
    lock: object

    def __init__(self, *args: object):
        if args and isinstance(args[0], list):
            self.disposables = args[0]
        else:
            self.disposables = list(args)
        self.is_disposed = False
        self.lock = RLock()

    def add(self, item: object) -> None:
        should_dispose: cython.bint = False
        with self.lock:
            if self.is_disposed:
                should_dispose = True
            else:
                self.disposables.append(item)
        if should_dispose:
            item.dispose()

    def remove(self, item: object) -> bool:
        if self.is_disposed:
            return False

        should_dispose: cython.bint = False
        with self.lock:
            if item in self.disposables:
                self.disposables.remove(item)
                should_dispose = True
        if should_dispose:
            item.dispose()
        return should_dispose

    def dispose(self) -> None:
        if self.is_disposed:
            return
        current: list
        with self.lock:
            self.is_disposed = True
            current = self.disposables
            self.disposables = []
        for d in current:
            d.dispose()

    def clear(self) -> None:
        current: list
        with self.lock:
            current = self.disposables
            self.disposables = []
        for d in current:
            d.dispose()

    def contains(self, item: object) -> bool:
        return item in self.disposables

    def __len__(self) -> int:
        return len(self.disposables)

    @property
    def length(self) -> int:
        return len(self.disposables)

    def __enter__(self):
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.dispose()


@cython.cclass
class BooleanDisposable:
    """Disposable that tracks whether it has been disposed."""

    is_disposed: cython.bint

    def __init__(self):
        self.is_disposed = False

    def dispose(self) -> None:
        self.is_disposed = True
