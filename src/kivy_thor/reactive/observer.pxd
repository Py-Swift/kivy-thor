from .disposable cimport SingleAssignmentDisposable

cdef class Observer:
    cdef public bint is_stopped
    cdef public object _handler_on_next
    cdef public object _handler_on_error
    cdef public object _handler_on_completed

    cpdef _on_next_core(self, object value)
    cpdef _on_error_core(self, object error)
    cpdef _on_completed_core(self)
    cpdef bint fail(self, object error)

cdef class AutoDetachObserver:
    cdef public bint is_stopped
    cdef public object _on_next
    cdef public object _on_error
    cdef public object _on_completed
    cdef public SingleAssignmentDisposable _subscription

    cpdef bint fail(self, object error)
