# cython: language_level=3
"""
ThorFbo – experimental FBO that extends RenderContext directly.

Unlike thorfbo (which wraps a plain Kivy Fbo and has to manually
save/restore GL state around every ThorVG sync), this version *is* the
framebuffer.  Key improvements:

 * apply() integrates ThorVG draw+sync into Kivy's own render cycle --
   no external refresh() call needed to get content onto the texture.
 * bind()/release() manage viewport, depth-test, blend state internally
   so callers never need glGetIntegerv / glViewport dance.
 * target() is re-called automatically on resize (size setter deletes
   and recreates the GL framebuffer, then re-binds GlCanvas to the
   new buffer_id).
 * Usable as a context manager (with tfbo: ...) just like Kivy Fbo.
"""

from libc.stdint cimport uintptr_t

from kivy.graphics.cgl cimport (
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
    GLuint, GLint,
    cgl,
)
from kivy.graphics.instructions cimport RenderContext
from kivy.graphics.texture cimport Texture
from kivy.graphics.transformation cimport Matrix as KivyMatrix
from kivy.graphics.stencil_instructions cimport (
    get_stencil_state, restore_stencil_state, reset_stencil_state,
)

from kivy.graphics.opengl import (
    glDisable, glEnable, glBlendFuncSeparate,
    GL_DEPTH_TEST, GL_BLEND,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE,
)
from kivy.weakmethod import WeakMethod
from kivy.utils import platform

from thorvg_cython.gl_canvas cimport GlCanvas

# -- EGL declarations ---------------------------------------------------------
cdef extern from "EGL/egl.h" nogil:
    ctypedef void  *EGLDisplay
    ctypedef void  *EGLSurface
    ctypedef void  *EGLContext
    ctypedef int    EGLint

    EGLContext eglGetCurrentContext()
    EGLDisplay eglGetCurrentDisplay()
    EGLSurface eglGetCurrentSurface(EGLint readdraw)

DEF EGL_DRAW = 0x3059

# -- module-level state (mirrors kivy Fbo) ------------------------------------
cdef list _fbo_stack = []

# opcodes flag used by RenderContext.apply
DEF GI_NEEDS_UPDATE = 1

# macOS desktop uses desktop GL, not GLES
cdef bint _IS_GLES = platform in ("ios", "android")

DEF GL_DEPTH_STENCIL_ATTACHMENT = 0x821A


cdef class ThorFbo(RenderContext):
    """Framebuffer with integrated ThorVG GlCanvas rendering.

    Usage::

        tfbo = ThorFbo(size=(800, 600))
        tfbo.gl_canvas.add(some_scene)

        with widget.canvas:
            widget.add(tfbo)
            Color(1, 1, 1, 1)
            Rectangle(size=tfbo.size, texture=tfbo.texture)

        # every frame, just flag an update -- apply() handles everything
        tfbo.flag_update()
    """

    def __cinit__(self, GlCanvas gl_canvas):
        self.gl_canvas = gl_canvas

    def __init__(self, *args, size=(1024, 1024), clear_color=(0, 0, 0, 0),
                 push_viewport=True, with_depthbuffer=False,
                 with_stencilbuffer=False, texture=None, **kwargs):
        RenderContext.__init__(self, *args, **kwargs)

        self.buffer_id = 0
        self.depthbuffer_id = 0
        self.stencilbuffer_id = 0
        self._width, self._height = size
        self.clear_color = clear_color
        self._depthbuffer_attached = <int>with_depthbuffer
        self._stencilbuffer_attached = <int>with_stencilbuffer
        self._push_viewport = <int>push_viewport
        self._is_bound = 0
        self._texture = texture
        self.observers = []

        if _IS_GLES and self._depthbuffer_attached:
            self._stencilbuffer_attached = 1

        self.create_fbo()
        self._bind_gl_canvas()

    def __dealloc__(self):
        self._dealloc_gl()

    # -- GL framebuffer management --------------------------------------------

    cdef str resolve_status(self, int status):
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
        return 'Unknown (status=0x{:04x})'.format(status)

    cdef void raise_exception(self, str message, int status=0):
        if status:
            message = '{}: {} ({})'.format(message, self.resolve_status(status), status)
        raise Exception(message)

    cdef void _dealloc_gl(self):
        cdef GLuint fb = self.buffer_id
        cdef GLuint rb
        if fb != 0:
            cgl.glDeleteFramebuffers(1, &fb)
            self.buffer_id = 0
        rb = self.depthbuffer_id or self.stencilbuffer_id
        if rb != 0:
            cgl.glDeleteRenderbuffers(1, &rb)
            self.depthbuffer_id = 0
            self.stencilbuffer_id = 0

    cdef void delete_fbo(self):
        self._texture = None
        self._dealloc_gl()

    cdef void create_fbo(self):
        cdef GLuint f_id = 0
        cdef GLint old_fid = 0
        cdef GLint old_rid = 0
        cdef int status
        cdef int do_clear = 0

        if self._texture is None:
            self._texture = Texture.create(size=(self._width, self._height))
            do_clear = 1

        self._texture.bind()

        cgl.glGenFramebuffers(1, &f_id)
        self.buffer_id = f_id
        cgl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, &old_fid)
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, self.buffer_id)

        if self._depthbuffer_attached or self._stencilbuffer_attached:
            cgl.glGetIntegerv(GL_RENDERBUFFER_BINDING, &old_rid)

        if self._depthbuffer_attached and self._stencilbuffer_attached:
            cgl.glGenRenderbuffers(1, &f_id)
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
            cgl.glGenRenderbuffers(1, &f_id)
            self.depthbuffer_id = f_id
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, self.depthbuffer_id)
            cgl.glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT16,
                                      self._width, self._height)
            cgl.glBindRenderbuffer(GL_RENDERBUFFER, old_rid)
            cgl.glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                          GL_RENDERBUFFER, self.depthbuffer_id)

        elif self._stencilbuffer_attached:
            cgl.glGenRenderbuffers(1, &f_id)
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

        cdef KivyMatrix projection_mat = KivyMatrix()
        projection_mat.view_clip(0.0, <float>self._width, 0.0, <float>self._height,
                                 -1.0, 1.0, 0)
        self.set_state('projection_mat', projection_mat)

    # -- GlCanvas target binding -----------------------------------------------

    cdef void _bind_gl_canvas(self):
        """Point the ThorVG GlCanvas at our GL framebuffer."""
        if self.gl_canvas is None:
            return

        cdef uintptr_t display = <uintptr_t>eglGetCurrentDisplay()
        cdef uintptr_t surface = <uintptr_t>eglGetCurrentSurface(EGL_DRAW)
        cdef uintptr_t context = <uintptr_t>eglGetCurrentContext()

        # target() may rebind the FBO internally -- save/restore
        cdef GLint saved_fbo = 0
        cgl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, &saved_fbo)

        (<GlCanvas>self.gl_canvas).target(
            display, surface, context,
            <int>self.buffer_id,
            <unsigned int>self._width,
            <unsigned int>self._height,
            2,
        )
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, saved_fbo)

    # -- bind / release --------------------------------------------------------

    cpdef bind(self):
        cdef GLint old_fid = 0

        if self._is_bound:
            self.raise_exception('ThorFbo already bound.')
        else:
            self._is_bound = 1

        if len(_fbo_stack) == 0:
            cgl.glGetIntegerv(GL_FRAMEBUFFER_BINDING, &old_fid)
            _fbo_stack.append(old_fid)
        _fbo_stack.append(<GLint>self.buffer_id)
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, self.buffer_id)

        if self._push_viewport:
            cgl.glGetIntegerv(GL_VIEWPORT, self._viewport)
            cgl.glViewport(0, 0, self._width, self._height)

        self._stencil_state = get_stencil_state()
        reset_stencil_state()

    cpdef release(self):
        if self._is_bound == 0:
            self.raise_exception('ThorFbo cannot be released (not bound).')
        else:
            self._is_bound = 0

        _fbo_stack.pop()
        cgl.glBindFramebuffer(GL_FRAMEBUFFER, <GLuint>_fbo_stack[-1])

        if self._push_viewport:
            cgl.glViewport(self._viewport[0], self._viewport[1],
                           self._viewport[2], self._viewport[3])

        restore_stencil_state(self._stencil_state)

        # Restore GL state that ThorVG's sync() may have changed
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ONE, GL_ONE)

    cpdef clear_buffer(self):
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

    # -- core render integration -----------------------------------------------

    cdef int apply(self) except -1:
        """Called by Kivy's render pipeline during canvas traversal.

        ThorVG update+draw+sync runs every time Kivy redraws the canvas,
        so callers only need canvas.ask_update() -- no separate refresh().
        """
        self.bind()
        self.gl_canvas.update()
        self.gl_canvas.draw(True)
        self.gl_canvas.sync()
        RenderContext.apply(self)
        self.release()
        return 0

    # -- reload after GL context loss ------------------------------------------

    cdef void reload(self) except *:
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

    # -- properties ------------------------------------------------------------

    @property
    def size(self):
        return (self._width, self._height)

    @size.setter
    def size(self, x):
        cdef int w, h
        w, h = x
        if w == self._width and h == self._height:
            return
        self._width = w
        self._height = h
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

    # -- context manager -------------------------------------------------------

    def __enter__(self):
        self.bind()
        return self

    def __exit__(self, *args):
        self.release()

    cpdef get_pixel_color(self, int wx, int wy):
        if wx > self._width or wy > self._height:
            return (0, 0, 0, 0)
        from kivy.graphics.opengl import glReadPixels as py_glReadPixels, GL_RGBA, GL_UNSIGNED_BYTE
        self.bind()
        data = py_glReadPixels(wx, wy, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE)
        self.release()
        return tuple(data)
