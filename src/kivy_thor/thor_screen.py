from kivy.uix.screenmanager import Screen
from kivy_thor.thorfbo import ThorFbo
from thorvg_cython import GlCanvas
from kivy.graphics import Callback
from kivy.graphics import Canvas as KivyCanvas

class ThorCanvas(KivyCanvas):
    fbo: ThorFbo
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def draw(self):
        super().draw()
        print("ThorCanvas draw called")


class ThorScreen(Screen):

    glcanvas: GlCanvas

    __children: list

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__children = []
        #self.canvas = ThorCanvas()
        with self.canvas:
            self.thor_fbo = ThorFbo(size=self.size)
        
        self.gl_canvas = self.thor_fbo.gl_canvas
        print(self.gl_canvas)
        print(f"[ThorScreen] initialized with size={self.size} thor_fbo={self.thor_fbo} gl_canvas={self.gl_canvas}")

    def on_callback(self, instruction):
        print("Callback called with instruction:", instruction, self)
        

    def on_size(self, _, size):
        self.thor_fbo.set_size(tuple(size))


    def add_widget(self, widget):
        self.__children.append(widget)
        widget.canvas_init(self.gl_canvas)

    def remove_widget(self, widget):
        self.__children.remove(widget)