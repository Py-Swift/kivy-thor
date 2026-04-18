from kivy.graphics.instructions cimport InstructionGroup
from kivy.graphics import Color, Rectangle
from thorvg_cython.gl_canvas cimport GlCanvas
from .thor_fbo cimport ThorFbo

cdef class ThorLayer(InstructionGroup):

    def __cinit__(self):
        self.gl_canvas = GlCanvas()
        self.fbo = ThorFbo(gl_canvas=self.gl_canvas)

    def __init__(self, size=(1024, 1024), **kwargs):
        super().__init__(**kwargs)
        self.fbo.size = size
        self.fbo_rect = Rectangle(texture=self.fbo.texture, size=size)
        self.add(self.fbo)
        self.add(Color(1, 1, 1, 1))
        self.add(self.fbo_rect)

    def set_size(self, size):
        self.fbo.size = size
        self.fbo_rect.size = size
        self.fbo_rect.texture = self.fbo.texture
