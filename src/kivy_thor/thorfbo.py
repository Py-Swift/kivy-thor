import sys

import cython
from cython.cimports.kivy.graphics.fbo import Fbo # type: ignore
#from cython.cimports.kivy.graphics.vertex_instructions import Rectangle # type: ignore
from cython.cimports.thorvg_cython.gl_canvas import GlCanvas # type: ignore
from kivy.graphics import Color, Rectangle, ClearColor, ClearBuffers
from kivy.graphics.opengl import (
    glGetIntegerv, glBindFramebuffer, glDisable, glEnable, glBlendFunc, glBlendFuncSeparate,
    glViewport,
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_BINDING, GL_VIEWPORT, GL_DEPTH_TEST, GL_BLEND,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE,
)
from kivy.clock import Clock
from thorvg_cython import Colorspace
from thorvg_cython.thorvg import Result
import ctypes
import sys

_EGL = None
if sys.platform == "darwin":
    import os
    import kivy as _kivy
    _egl_path = os.path.join(os.path.dirname(_kivy.__file__), ".dylibs", "libEGL.dylib")
    if os.path.exists(_egl_path):
        _EGL = ctypes.CDLL(_egl_path)
        _EGL.eglGetCurrentContext.restype = ctypes.c_size_t
        _EGL.eglGetCurrentDisplay.restype = ctypes.c_size_t
        _EGL.eglGetCurrentSurface.restype = ctypes.c_size_t


class ThorFbo:

    def __cinit__(self):
        self.fbo = Fbo()
        self.gl_canvas = GlCanvas()
        self.fbo_rect = Rectangle() # type: ignore

    def __init__(self, size=(1024, 1024), on_ready=None, **kwargs):
        self._on_ready = on_ready
        super().__init__(**kwargs)
        self.fbo.size = size
        self.fbo_rect.size = size
        self.fbo_rect.texture = self.fbo.texture
        self.add(self.fbo)
        self.add(Color(1, 1, 1, 1))
        self.add(self.fbo_rect)

        self._init_gl_canvas(0)

    def _init_gl_canvas(self, dt):
        self._bind_target()
        if self._on_ready is not None:
            self._on_ready()

    def _bind_target(self):
        if self.gl_canvas is None:
            return
        display = 0
        surface = 0
        context = 0
        if sys.platform == "darwin":
            context = _EGL.eglGetCurrentContext()
            display = _EGL.eglGetCurrentDisplay()
            surface = _EGL.eglGetCurrentSurface(0x3059)
        # target() ends with glBindFramebuffer(Kivy's FBO) as a side-effect,
        # which corrupts Kivy's GL state — window.clear() then clears the FBO
        # texture instead of the screen.  Save and restore the binding.
        saved_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING)[0])
        result = self.gl_canvas.target(
            display, surface, context,
            cython.cast(cython.int, self.fbo.buffer_id),
            cython.cast(cython.uint, self.fbo._width),
            cython.cast(cython.uint, self.fbo._height),
            2,
        )
        glBindFramebuffer(GL_FRAMEBUFFER, saved_fbo)

    def refresh(self, clear: bool = True) -> None:
        self.gl_canvas.update()
        self.gl_canvas.draw(clear)
        saved_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING)[0])
        vp = glGetIntegerv(GL_VIEWPORT)
        self.gl_canvas.sync()
        glBindFramebuffer(GL_FRAMEBUFFER, saved_fbo)
        glViewport(int(vp[0]), int(vp[1]), int(vp[2]), int(vp[3]))
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE)
        

    def set_size(self, size: tuple[int, int]) -> None:
        self.fbo.size = size        # fbo.size = size calls create_fbo() → new buffer_id + new texture.
        # Must re-bind ThorVG target to the new buffer_id, otherwise sync()
        # keeps rendering into the old (now orphaned) GL framebuffer.
        self._bind_target()
        self.fbo_rect.size = size
        self.fbo_rect.texture = self.fbo.texture
        #print(f"[ThorFbo] set_size={size} new_buffer_id={self.fbo.buffer_id} texture_size={self.fbo.texture.size}")