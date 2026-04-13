# cython: language_level=3
from kivy.graphics.instructions cimport InstructionGroup
from kivy.graphics.fbo cimport Fbo
from kivy.graphics import Color, Rectangle
from thorvg_cython.gl_canvas cimport GlCanvas
from thorvg_cython import Colorspace


cdef class ThorFbo(InstructionGroup):

    cdef public Fbo fbo
    cdef public GlCanvas gl_canvas

    def __cinit__(self, *args, **kwargs):
        self.fbo = Fbo()
        self.gl_canvas = GlCanvas()

    def __init__(self, size=(1024, 1024), **kwargs):
        super().__init__(**kwargs)
        self.fbo.size = size
        self.gl_canvas.target(
            0, 0, 0,
            self.fbo.buffer_id,
            <unsigned int>self.fbo._width, <unsigned int>self.fbo._height,
            Colorspace.ABGR8888S,
        )
        self.add(self.fbo)
        self.add(Color(1, 1, 1, 1))
        self.add(Rectangle(size=size, texture=self.fbo.texture))
