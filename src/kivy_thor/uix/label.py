__all__ = ('Label', )

from kivy.properties import (
    StringProperty, NumericProperty, ListProperty, OptionProperty,
    BooleanProperty, ReferenceListProperty)

from .widget import Widget
from thorvg_cython import Text, Scene, GlCanvas, TextWrap, Matrix as TvgMatrix


# Horizontal-alignment → ThorVG text x anchor (0=left, 0.5=center, 1=right)
_HALIGN_X = {'left': 0.0, 'center': 0.5, 'right': 1.0}
# Vertical-alignment → ThorVG text y anchor (0=top, 0.5=middle, 1=bottom)
_VALIGN_Y = {'top': 0.0, 'middle': 0.5, 'bottom': 1.0}


class Label(Widget):
    '''Label widget — renders text via ThorVG.

    Usage::

        lbl = Label(text='Hello', font_size=24, color=(1, 1, 0, 1))

    The label participates in the thor-canvas tree via the standard
    ``canvas_init`` / ``scene_init`` / ``canvas_remove`` / ``scene_remove``
    / ``canvas_update`` protocol.  It adds its Text paint object directly
    into the parent scene — no intermediate Scene wrapper needed.
    '''

    text = StringProperty('')
    font_name = StringProperty('')
    font_size = NumericProperty(16)
    bold = BooleanProperty(False)
    italic = BooleanProperty(False)

    # RGBA 0-1 floats
    color = ListProperty([1, 1, 1, 1])

    halign = OptionProperty('left', options=['left', 'center', 'right'])
    valign = OptionProperty('middle', options=['top', 'middle', 'bottom'])

    padding_x = NumericProperty(0)
    padding_y = NumericProperty(0)
    padding = ReferenceListProperty(padding_x, padding_y)

    def __init__(self, **kwargs):
        self._t = Text()
        super(Label, self).__init__(**kwargs)

        self.fbind('font_name',   self._on_font_name)
        self.fbind('font_size',   self._on_font_size)
        self.fbind('text',        self._on_text)
        self.fbind('color',       self._on_color)
        self.fbind('italic',      self._on_italic)
        self.fbind('halign',      self._on_align)
        self.fbind('valign',      self._on_align)
        self.fbind('padding_x',   self._on_layout)
        self.fbind('padding_y',   self._on_layout)
        self.fbind('size',        self._on_layout)
        self.fbind('pos',         self._on_pos)

    # ------------------------------------------------------------------
    # Per-property updaters
    # ------------------------------------------------------------------

    def _on_font_name(self, *_):
        if self.font_name:
            self._t.set_font(self.font_name)

    def _on_font_size(self, *_):
        self._t.set_size(float(self.font_size))

    def _on_text(self, *_):
        self._t.set_text(self.text)

    def _on_color(self, *_):
        r, g, b = (int(c * 255) for c in self.color[:3])
        self._t.set_color(r, g, b)

    def _on_italic(self, *_):
        self._t.set_italic(10.0 if self.italic else 0.0)

    def _on_align(self, *_):
        self._t.align(_HALIGN_X.get(self.halign, 0.0), _VALIGN_Y.get(self.valign, 0.5))

    def _on_layout(self, *_):
        lw = max(1.0, self.width - self.padding_x * 2)
        lh = max(1.0, self.height - self.padding_y * 2)
        self._t.layout(lw, lh)
        self._t.wrap_mode(TextWrap.WORD)
        self._on_pos()

    def _on_pos(self, *_):
        self._t.set_transform(TvgMatrix(
            e13=self.x + self.padding_x,
            e23=self.y + self.padding_y,
        ))

    def _init_all(self):
        '''Push all current property values to the Text object at once.'''
        t = self._t
        if self.font_name:
            t.set_font(self.font_name)
        t.set_size(float(self.font_size))
        t.set_text(self.text)
        r, g, b = (int(c * 255) for c in self.color[:3])
        t.set_color(r, g, b)
        t.set_italic(10.0 if self.italic else 0.0)
        lw = max(1.0, self.width - self.padding_x * 2)
        lh = max(1.0, self.height - self.padding_y * 2)
        t.layout(lw, lh)
        t.wrap_mode(TextWrap.WORD)
        t.align(_HALIGN_X.get(self.halign, 0.0), _VALIGN_Y.get(self.valign, 0.5))
        t.set_transform(TvgMatrix(
            e13=self.x + self.padding_x,
            e23=self.y + self.padding_y,
        ))

    # ------------------------------------------------------------------
    # Thor-canvas protocol
    # ------------------------------------------------------------------

    def canvas_init(self, canvas: GlCanvas):
        self._init_all()
        canvas.add(self._t)

    def scene_init(self, scene: Scene):
        self._init_all()
        scene.add(self._t)

    def canvas_remove(self, canvas: GlCanvas):
        canvas.remove(self._t)

    def scene_remove(self, scene: Scene):
        scene.remove(self._t)

    def canvas_update(self, dt: float) -> bool:
        return False
