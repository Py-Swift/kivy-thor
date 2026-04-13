cdef class Disposable:
    cdef public bint is_disposed
    cdef public object action
    cdef public object lock

cdef class SingleAssignmentDisposable:
    cdef public bint is_disposed
    cdef public object current
    cdef public object lock

cdef class SerialDisposable:
    cdef public bint is_disposed
    cdef public object current
    cdef public object lock

cdef class CompositeDisposable:
    cdef public bint is_disposed
    cdef public list disposables
    cdef public object lock

cdef class BooleanDisposable:
    cdef public bint is_disposed
