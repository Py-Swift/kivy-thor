# rewrite RxPY as cython module in kivy-thor

https://github.com/reactivex/rxpy


try rewrite as much possible as 

cdef class
cdef type var

if cdef class nakes sense and is possible


# when it makes sense
def func(self, a: double):
    self._func(<double>a)

#cython only, and added to .pxd
cdef _func(self, a: cython.double)


atleast sooo cython help optimize when ever possible 