__all__ = ('Button', )

from kivy.properties import ListProperty, NumericProperty
from kivy.uix.behaviors import ButtonBehavior

from kivy_thor.uix.label import Label
from thorvg_cython import Shape, Scene, GlCanvas, Matrix as TvgMatrix


class Button(ButtonBehavior, Label):

    background_color        = ListProperty([0.2, 0.2, 0.2, 1])
    background_color_down   = ListProperty([0.4, 0.4, 0.4, 1])
    border_radius           = NumericProperty(0)

    def __init__(self, **kwargs):
        self._bg = Shape()
        super(Button, self).__init__(**kwargs)

        self.fbind('background_color',      self._on_background_color)
        self.fbind('background_color_down', self._on_background_color)
        self.fbind('state',                 self._on_background_color)
        self.fbind('border_radius',         self._on_bg_shape)
        self.fbind('size',                  self._on_bg_shape)
        self.fbind('pos',                   self._on_bg_pos)

    # ------------------------------------------------------------------
    # Background shape updaters
    # ------------------------------------------------------------------

    def _sync_bg(self):
        bg = self._bg
        bg.reset()
        r = self.border_radius
        bg.append_rect(0.0, 0.0, float(self.width), float(self.height), r, r)
        col = self.background_color_down if self.state == 'down' else self.background_color
        cr, cg, cb, ca = (int(c * 255) for c in col)
        bg.set_fill_color(cr, cg, cb, ca)
        bg.set_transform(TvgMatrix(e13=self.x, e23=self.y))

    def _on_bg_shape(self, *_):
        self._bg.reset()
        r = self.border_radius
        self._bg.append_rect(0.0, 0.0, float(self.width), float(self.height), r, r)
        self._on_bg_pos()

    def _on_background_color(self, *_):
        col = self.background_color_down if self.state == 'down' else self.background_color
        cr, cg, cb, ca = (int(c * 255) for c in col)
        self._bg.set_fill_color(cr, cg, cb, ca)

    def _on_bg_pos(self, *_):
        self._bg.set_transform(TvgMatrix(e13=self.x, e23=self.y))

    # ------------------------------------------------------------------
    # Thor-canvas protocol — bg first so text draws on top
    # ------------------------------------------------------------------

    def canvas_init(self, canvas: GlCanvas):
        self._sync_bg()
        canvas.add(self._bg)
        super().canvas_init(canvas)

    def scene_init(self, scene: Scene):
        self._sync_bg()
        scene.add(self._bg)
        super().scene_init(scene)

    def canvas_remove(self, canvas: GlCanvas):
        super().canvas_remove(canvas)
        canvas.remove(self._bg)

    def scene_remove(self, scene: Scene):
        super().scene_remove(scene)
        scene.remove(self._bg)

    def canvas_update(self, dt: float) -> bool:
        return False
