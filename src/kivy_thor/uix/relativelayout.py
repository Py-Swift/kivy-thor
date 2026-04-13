__all__ = ('RelativeLayout', )

from .floatlayout import FloatLayout
from thorvg_cython import Scene, GlCanvas

class RelativeLayout(FloatLayout):
    '''RelativeLayout: children positioned relative to the layout's own origin.

    Identical to FloatLayout except that child coordinates are relative —
    a child at (0, 0) stays at the layout's bottom-left corner regardless of
    where the layout itself is positioned on screen.
    '''

    def __init__(self, **kw):
        
        super(RelativeLayout, self).__init__(**kw)
        funbind = self.funbind
        trigger = self._trigger_layout
        # pos changes don't trigger re-layout; children move implicitly via
        # the coordinate transform below
        funbind('pos', trigger)
        funbind('pos_hint', trigger)
        

    def do_layout(self, *args):
        super(RelativeLayout, self).do_layout(pos=(0, 0))

    def to_parent(self, x, y, **k):
        return (x + self.x, y + self.y)

    def to_local(self, x, y, **k):
        return (x - self.x, y - self.y)

    def _apply_transform(self, m, pos=None):
        m.translate(self.x, self.y, 0)
        return super(RelativeLayout, self)._apply_transform(m, (0, 0))

    def on_motion(self, etype, me):
        if me.type_id in self.motion_filter and 'pos' in me.profile:
            me.push()
            me.apply_transform_2d(self.to_local)
            ret = super().on_motion(etype, me)
            me.pop()
            return ret
        return super().on_motion(etype, me)

    def on_touch_down(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_local)
        ret = super(RelativeLayout, self).on_touch_down(touch)
        touch.pop()
        return ret

    def on_touch_move(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_local)
        ret = super(RelativeLayout, self).on_touch_move(touch)
        touch.pop()
        return ret

    def on_touch_up(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_local)
        ret = super(RelativeLayout, self).on_touch_up(touch)
        touch.pop()
        return ret
    

    
