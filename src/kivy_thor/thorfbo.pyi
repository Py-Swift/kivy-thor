from kivy.graphics.fbo import Fbo
from kivy.graphics.instructions import InstructionGroup
from thorvg_cython import GlCanvas

class ThorFbo(InstructionGroup):
    fbo: Fbo
    gl_canvas: GlCanvas

    def __init__(self, size: tuple[int, int] = ..., **kwargs: object) -> None: ...
