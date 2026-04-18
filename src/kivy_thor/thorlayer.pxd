from kivy.graphics.instructions cimport InstructionGroup
from thorvg_cython.gl_canvas cimport GlCanvas
from .thor_fbo cimport ThorFbo

cdef class ThorLayer(InstructionGroup):
    cdef public GlCanvas gl_canvas
    cdef public ThorFbo fbo
    cdef public object fbo_rect