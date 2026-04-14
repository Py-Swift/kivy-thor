"""
ThorFbo – experimental FBO that extends RenderContext directly.

Unlike thorfbo.py (which wraps a plain Kivy Fbo and has to manually
save/restore GL state around every ThorVG sync), this version *is* the
framebuffer.  Key improvements:

 • apply() integrates ThorVG draw+sync into Kivy's own render cycle —
   no external refresh() call needed to get content onto the texture.
 • bind()/release() manage viewport, depth-test, blend state internally
   so callers never need glGetIntegerv / glViewport dance.
 • target() is re-called automatically on resize (size setter deletes
   and recreates the GL framebuffer, then re-binds GlCanvas to the
   new buffer_id).
 • Usable as a context manager (with tfbo: ...) just like Kivy Fbo.
"""

import sys
import ctypes
import os

import cython
from cython.cimports.kivy.graphics.cgl import (  # type: ignore
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_BINDING, GL_FRAMEBUFFER_COMPLETE,
    GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT,
    GL_FRAMEBUFFER_INCOMPLETE_DIMENSIONS,
    GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT,
    GL_FRAMEBUFFER_UNSUPPORTED,
    GL_FRAMEBUFFER_UNDEFINED_OES,
    GL_RENDERBUFFER, GL_RENDERBUFFER_BINDING,
    GL_COLOR_ATTACHMENT0,
    GL_DEPTH_ATTACHMENT, GL_STENCIL_ATTACHMENT,
    GL_DEPTH_COMPONENT16, GL_STENCIL_INDEX8,
    GL_DEPTH24_STENCIL8_OES,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_STENCIL_BUFFER_BIT,
    GL_VIEWPORT,
    cgl,
)
from cython.cimports.kivy.graphics.cgl import GLuint, GLint  # type: ignore
from cython.cimports.kivy.graphics.instructions import RenderContext  # type: ignore
from cython.cimports.kivy.graphics.texture import Texture  # type: ignore
from cython.cimports.kivy.graphics.transformation import Matrix as KivyMatrix  # type: ignore
from cython.cimports.kivy.graphics.context import get_context  # type: ignore
from cython.cimports.kivy.graphics.stencil_instructions import (  # type: ignore
    get_stencil_state, restore_stencil_state, reset_stencil_state,
)

from kivy.graphics import Color, Rectangle
from kivy.graphics.texture import Texture as PyTexture
from kivy.graphics.opengl import (
    glDisable, glEnable, glBlendFuncSeparate,
    GL_DEPTH_TEST, GL_BLEND,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE,
)
from kivy.weakmethod import WeakMethod
from kivy.utils import platform

from thorvg_cython.gl_canvas import GlCanvas  # type: ignore

# ── EGL helpers (macOS/ANGLE) ────────────────────────────────────────────────
_EGL = None
if sys.platform == "darwin":
    import kivy as _kivy
    _egl_path = os.path.join(os.path.dirname(_kivy.__file__), ".dylibs", "libEGL.dylib")
    if os.path.exists(_egl_path):
        _EGL = ctypes.CDLL(_egl_path)
        _EGL.eglGetCurrentContext.restype = ctypes.c_size_t
        _EGL.eglGetCurrentDisplay.restype = ctypes.c_size_t
        _EGL.eglGetCurrentSurface.restype = ctypes.c_size_t

# ── module-level state (mirrors kivy Fbo) ────────────────────────────────────
_fbo_stack: list = []

# opcodes flag used by RenderContext.apply
GI_NEEDS_UPDATE = 1  # from kivy/graphics/opcodes.pxi

# macOS desktop uses desktop GL, not GLES
_IS_GLES = False
if platform == "ios" or platform == "android":
    _IS_GLES = True

GL_DEPTH_STENCIL_ATTACHMENT: cython.int = 0x821A


@cython.cclass
class ThorFbo(RenderContext):
    """Framebuffer with integrated ThorVG GlCanvas rendering.

    Usage::

        tfbo = ThorFbo(size=(800, 600))
        # add thorvg shapes to tfbo.gl_canvas
        tfbo.gl_canvas.add(some_scene)

        # in your widget canvas:
        with widget.canvas:
            widget.add(tfbo)
            Color(1, 1, 1, 1)
            Rectangle(size=tfbo.size, texture=tfbo.texture)

        # every frame, just flag an update — apply() handles everything
        tfbo.flag_update()
    """

    gl_canvas: object

    _width: cython.int
    _height: cython.int
    _depthbuffer_attached: cython.int
    _stencilbuffer_attached: cython.int
    _push_viewport: cython.int
    _clear_color: cython.float[4]
    buffer_id: cython.uint
    depthbuffer_id: cython.uint
    stencilbuffer_id: cython.uint
    _viewport: cython.int[4]
    _texture: Texture
    _is_bound: cython.int
    _stencil_state: object
    observers: list

    def __init__(self, *args, size=(1024, 1024), clear_color=(0, 0, 0, 0),
                 push_viewport=True, with_depthbuffer=False,
                 with_stencilbuffer=False, texture=None, **kwargs):
        get_context().register_fbo(self)
        RenderContext.__init__(self, *args, **kwargs)

        self.buffer_id = 0
        self.depthbuffer_id = 0
        self.stencilbuffer_id = 0
        self._width, self._height = size
        self.clear_color = clear_color
        self._depthbuffer_attached = int(with_depthbuffer)
        self._stencilbuffer_attached = int(with_stencilbuffer)
        self._push_viewport = int(push_viewport)
        self._is_bound = 0
        self._texture = texture
        self.observers = []

        if _IS_GLES and self._depthbuffer_attached:
            self._stencilbuffer_attached = 1

        self.gl_canvas = GlCanvas()

        self.create_fbo()
        self._bind_gl_canvas()

    def __dealloc__(self):
        get_context().dealloc_fbo(self)

    # ── GL framebuffer management ─────────────────────────────────────────

    @cython.cfunc
    def resolve_status(self, status: cython.int) -> str:
        if status == GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT:
            return 'Incomplete attachment'
        elif status == GL_FRAMEBUFFER_INCOMPLETE_DIMENSIONS:
            return 'Incomplete dimensions'
        elif status == GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT:
            return 'Incomplete missing attachment'
        elif status == GL_FRAMEBUFFER_UNSUPPORTED:
            return 'Unsupported'
        elif status == GL_FRAMEBUFFER_UNDEFINED_OES:
            return 'Undefined framebuffer'
        return f'Unknown (status={status:#x})'

    @cython.cfunc
    def raise_exception(self, message: str, status: cython.int = 0):
        if status:
            message += f': {self.resolve_status(status)} ({status})'
        raise Exception(message)

    @cython.cfunc
    def delete_fbo(self):
        self._texture = None
        get_context().dealloc_fbo(self)
        self.buffer_id = 0
        self.depthbuffer_id = 0

    @cython.cfunc
    def create_fbo(self):
        f_id: cython.uint = 0
        old_fid: cython.int = 0
        old_rid: cython.int = 0
        status: cython.int
        do_clear: cython.int = 0

        if self._texture is None:
            self._texture = PyTexture.create(size=(self._width, self._height))
            do_clear = 1

        self._texture.bind()

        cgl.glGenFramebuffers(1, cython.address(f_id))
        self.buffer_id = f_id
        cgl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, cython.address(old_fid))
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, self.buffer_id)

        if self._depthbuffer_attached or self._stencilbuffer_attached:
            cgl.glGetIntegerv(GL_RENDERBUFFER_BINDING, cython.address(old_rid))

        if self._depthbuffer_attached and self._stencilbuffer_attached:
            cgl.glGenRenderbuffers(1, cython.address(f_id))
            self.depthbuffer_id = f_id
            self.stencilbuffer_id = f_id
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, f_id)
            cgl.glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH24_STENCIL8_OES,
                                      self._width, self._height)
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, old_rid)
            if _IS_GLES:
                cgl.glFramebufferRenderbuffer(
                    GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                    GL_RENDERBUFFER, f_id)
            else:
                cgl.glFramebufferRenderbuffer(
                    GL_FRAMEBUFFER, GL_DEPTH_STENCIL_ATTACHMENT,
                    GL_RENDERBUFFER, f_id)

        elif self._depthbuffer_attached:
            cgl.glGenRenderbuffers(1, cython.address(f_id))
            self.depthbuffer_id = f_id
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, self.depthbuffer_id)
            cgl.glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT16,
                                      self._width, self._height)
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, old_rid)
            cgl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                          GL_RENDERBUFFER, self.depthbuffer_id)

        elif self._stencilbuffer_attached:
            cgl.glGenRenderbuffers(1, cython.address(f_id))
            self.stencilbuffer_id = f_id
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, self.stencilbuffer_id)
            cgl.glRenderbufferStorage(GL_RENDERBUFFER, GL_STENCIL_INDEX8,
                                      self._width, self._height)
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, old_rid)
            cgl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_STENCIL_ATTACHMENT,
                                          GL_RENDERBUFFER, self.stencilbuffer_id)

        cgl.glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                                   self._texture._target, self._texture._id, 0)

        status = cgl.glCheckFramebufferStatus(GL_FRAMEBUFFER)
        if status != GL_FRAMEBUFFER_COMPLETE:
            self.raise_exception('ThorFbo init failed', status)

        if do_clear:
            self.clear_buffer()

        cgl.glBindFramebuffer(GL_FRAMEBUFFER, old_fid)

        projection_mat: KivyMatrix = KivyMatrix()
        projection_mat.view_clip(0.0, self._width, 0.0, self._height, -1.0, 1.0, 0)
        self.set_state('projection_mat', projection_mat)

    # ── GlCanvas target binding ───────────────────────────────────────────

    def _bind_gl_canvas(self):
        """Point the ThorVG GlCanvas at our GL framebuffer."""
        if self.gl_canvas is None:
            return
        display: cython.size_t = 0
        surface: cython.size_t = 0
        context: cython.size_t = 0
        if sys.platform == "darwin" and _EGL is not None:
            context = _EGL.eglGetCurrentContext()
            display = _EGL.eglGetCurrentDisplay()
            surface = _EGL.eglGetCurrentSurface(0x3059)
        # target() binds our FBO as side-effect — save/restore
        saved_fbo: cython.int = 0
        cgl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, cython.address(saved_fbo))
        self.gl_canvas.target(
            display, surface, context,
            cython.cast(cython.int, self.buffer_id),
            cython.cast(cython.uint, self._width),
            cython.cast(cython.uint, self._height),
            2,
        )
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, saved_fbo)

    # ── bind / release ────────────────────────────────────────────────────

    @cython.ccall
    def bind(self):
        if self._is_bound:
            self.raise_exception('ThorFbo already bound.')
        else:
            self._is_bound = 1

        old_fid: cython.int = 0
        if len(_fbo_stack) == 0:
            cgl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, cython.address(old_fid))
            _fbo_stack.append(old_fid)
        _fbo_stack.append(cython.cast(cython.int, self.buffer_id))
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, self.buffer_id)

        if self._push_viewport:
            cgl.glGetIntegerv(GL_VIEWPORT, cython.cast(cython.p_int, self._viewport))
            cgl.glViewport(0, 0, self._width, self._height)

        self._stencil_state = get_stencil_state()
        reset_stencil_state()

    @cython.ccall
    def release(self):
        if self._is_bound == 0:
            self.raise_exception('ThorFbo cannot be released (not bound).')
        else:
            self._is_bound = 0

        _fbo_stack.pop()
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, _fbo_stack[-1])

        if self._push_viewport:
            cgl.glViewport(self._viewport[0], self._viewport[1],
                           self._viewport[2], self._viewport[3])

        restore_stencil_state(self._stencil_state)

        # Restore GL state that ThorVG's sync() may have changed
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE)

    @cython.ccall
    def clear_buffer(self):
        cgl.glClearColor(self._clear_color[0], self._clear_color[1],
                         self._clear_color[2], self._clear_color[3])
        if self._depthbuffer_attached and self._stencilbuffer_attached:
            cgl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
        elif self._depthbuffer_attached:
            cgl.glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        elif self._stencilbuffer_attached:
            cgl.glClear(GL_COLOR_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)
        else:
            cgl.glClear(GL_COLOR_BUFFER_BIT)

    # ── core render integration ───────────────────────────────────────────

    @cython.cfunc
    def apply(self) -> cython.int:
        """Called by Kivy's render pipeline when the instruction tree is dirty.

        This is the key improvement: ThorVG update+draw+sync happens
        *inside* the normal Kivy draw cycle, while we already have the
        FBO bound.  No manual refresh() + glGetIntegerv dance needed.
        """
        if self.flags & GI_NEEDS_UPDATE:
            self.bind()
            # Let ThorVG render into our FBO
            self.gl_canvas.update()
            self.gl_canvas.draw(True)
            self.gl_canvas.sync()
            # Run any Kivy children (Color, Rectangle, etc.) if present
            RenderContext.apply(self)
            self.release()
            self.flag_update_done()
        return 0

    def refresh(self):
        """Manual trigger — just flags the instruction as dirty.

        The actual GL work happens in apply() on the next Kivy draw.
        """
        self.flag_update()

    # ── reload after GL context loss ──────────────────────────────────────

    @cython.cfunc
    def reload(self):
        self.create_fbo()
        self._bind_gl_canvas()
        self.flag_update()
        for callback in self.observers[:]:
            method = callback()
            if method is None:
                self.observers.remove(callback)
                continue
            method(self)

    def add_reload_observer(self, callback):
        self.observers.append(WeakMethod(callback))

    def remove_reload_observer(self, callback):
        for cb in self.observers[:]:
            method = cb()
            if method is None or method is callback:
                self.observers.remove(cb)

    # ── properties ────────────────────────────────────────────────────────

    @property
    def size(self):
        return (self._width, self._height)

    @size.setter
    def size(self, x):
        w: cython.int
        h: cython.int
        w, h = x
        if w == self._width and h == self._height:
            return
        self._width, self._height = w, h
        self.delete_fbo()
        self.create_fbo()
        self._bind_gl_canvas()
        self.flag_data_update()

    @property
    def clear_color(self):
        return (self._clear_color[0], self._clear_color[1],
                self._clear_color[2], self._clear_color[3])

    @clear_color.setter
    def clear_color(self, x):
        x = list(x)
        if len(x) != 4:
            raise Exception('clear_color must be a list/tuple of 4 entries.')
        self._clear_color[0] = x[0]
        self._clear_color[1] = x[1]
        self._clear_color[2] = x[2]
        self._clear_color[3] = x[3]

    @property
    def texture(self):
        return self._texture

    # ── context manager ───────────────────────────────────────────────────

    def __enter__(self):
        self.bind()
        return self

    def __exit__(self, *args):
        self.release()

    @cython.ccall
    def get_pixel_color(self, wx: cython.int, wy: cython.int):
        if wx > self._width or wy > self._height:
            return (0, 0, 0, 0)
        from kivy.graphics.opengl import glReadPixels as py_glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
        self.bind()
        data = py_glReadPixels(wx, wy, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE)
        self.release()
        return tuple(data)
