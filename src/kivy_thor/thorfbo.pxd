from kivy.graphics.instructions cimport InstructionGroup
from kivy.graphics.fbo cimport Fbo
from thorvg_cython.gl_canvas cimport GlCanvas

cdef class ThorFbo(InstructionGroup):
    cdef public Fbo fbo
    cdef public object gl_canvas
    cdef public object fbo_rect
    cdef public object _on_ready