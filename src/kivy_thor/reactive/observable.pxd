cdef class Observable:
    cdef public object lock
    cdef public object _subscribe_fn

    cpdef _subscribe_core(self, object observer, object scheduler=*)
