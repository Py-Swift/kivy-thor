from kivy.uix.screenmanager import Screen
#from kivy_thor.thorfbo import ThorFbo
from kivy_thor.thorlayer import ThorLayer
from thorvg_cython import GlCanvas
from kivy.graphics import Callback
from kivy.graphics import Canvas as KivyCanvas

from kivy.graphics import Color, Rectangle

class ThorCanvas(KivyCanvas):
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)


    def draw(self):
        super().draw()
        print("ThorCanvas draw called")


class ThorScreen(Screen):

    glcanvas: GlCanvas
    t_layer: ThorLayer

    __children: list

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.__children = []
        with self.canvas:
            self.t_layer = ThorLayer(size=self.size)
        self.gl_canvas = self.t_layer.gl_canvas

    def on_callback(self, instruction):
        print("Callback called with instruction:", instruction, self)
        
    def on_size(self, _, size):
        self.t_layer.set_size(tuple(size))

    def add_widget(self, widget):
        self.__children.append(widget)
        widget.canvas_init(self.gl_canvas)

    def remove_widget(self, widget):
        self.__children.remove(widget)