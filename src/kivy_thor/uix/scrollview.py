__all__ = ('ScrollView',)

from functools import partial
from math import isclose
from enum import Enum

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.config import Config
from kivy.factory import Factory
from kivy.metrics import dp
from kivy.effects.dampedscroll import DampedScrollEffect
from kivy.properties import (
    NumericProperty,
    BooleanProperty,
    AliasProperty,
    ObjectProperty,
    ListProperty,
    ReferenceListProperty,
    OptionProperty,
    ColorProperty,
)
from kivy.uix.behaviors import FocusBehavior

from kivy_thor.uix.widget import Widget
from thorvg_cython import Scene, Shape, GlCanvas, Matrix as TvgMatrix


# ── re-export helper enums / classes from Kivy ScrollView ─────────────────
from kivy.uix.scrollview import (
    ScrollMode,
    DelegationMode,
    ScrollViewHierarchy,
    _BOUNDARY_THRESHOLD,
)

_scroll_timeout = _scroll_distance = 0
if Config:
    _scroll_timeout = Config.getint('widgets', 'scroll_timeout')
    _scroll_distance = '{}sp'.format(Config.getint('widgets', 'scroll_distance'))


class ScrollView(Widget):
    '''ScrollView — Kivy scroll logic + ThorVG clip/transform rendering.

    Clipping:  a rect Shape is used as clipper on the content Scene.
    Scrolling: content Scene transform (e13/e23) is updated each frame via
               update_from_scroll(), replacing Kivy's PushMatrix/Translate.
    '''

    # ── scroll properties (verbatim from Kivy ScrollView) ─────────────────
    scroll_distance = NumericProperty(_scroll_distance)
    scroll_wheel_distance = NumericProperty('20sp')
    scroll_timeout = NumericProperty(_scroll_timeout)
    scroll_x = NumericProperty(0.0)
    scroll_y = NumericProperty(1.0)
    do_scroll_x = BooleanProperty(True)
    do_scroll_y = BooleanProperty(True)

    def _get_do_scroll(self):
        return (self.do_scroll_x, self.do_scroll_y)

    def _set_do_scroll(self, value):
        if isinstance(value, (list, tuple)):
            self.do_scroll_x, self.do_scroll_y = value
        else:
            self.do_scroll_x = self.do_scroll_y = bool(value)

    do_scroll = AliasProperty(_get_do_scroll, _set_do_scroll,
                               bind=('do_scroll_x', 'do_scroll_y'), cache=True)

    always_overscroll = BooleanProperty(True)

    def _get_vbar(self):
        if self._viewport is None:
            return 0, 1.0
        vh = self._viewport.height
        h = self.height
        if vh < h or vh == 0:
            return 0, 1.0
        ph = max(0.01, h / float(vh))
        sy = min(1.0, max(0.0, self.scroll_y))
        py = (1.0 - ph) * sy
        return (py, ph)

    vbar = AliasProperty(_get_vbar,
                          bind=('scroll_y', '_viewport', 'viewport_size', 'height'),
                          cache=True)

    def _get_hbar(self):
        if self._viewport is None:
            return 0, 1.0
        vw = self._viewport.width
        w = self.width
        if vw < w or vw == 0:
            return 0, 1.0
        pw = max(0.01, w / float(vw))
        sx = min(1.0, max(0.0, self.scroll_x))
        px = (1.0 - pw) * sx
        return (px, pw)

    hbar = AliasProperty(_get_hbar,
                          bind=('scroll_x', '_viewport', 'viewport_size', 'width'),
                          cache=True)

    bar_color          = ColorProperty([0.7, 0.7, 0.7, 0.9])
    bar_inactive_color = ColorProperty([0.7, 0.7, 0.7, 0.2])
    bar_width          = NumericProperty('2dp')
    bar_pos_x          = OptionProperty('bottom', options=('top', 'bottom'))
    bar_pos_y          = OptionProperty('right',  options=('left', 'right'))
    bar_pos            = ReferenceListProperty(bar_pos_x, bar_pos_y)
    bar_margin         = NumericProperty(0)

    effect_cls  = ObjectProperty(DampedScrollEffect, allownone=True)
    effect_x    = ObjectProperty(None, allownone=True)
    effect_y    = ObjectProperty(None, allownone=True)

    viewport_size = ListProperty([0, 0])

    scroll_type = OptionProperty(
        ['content'],
        options=(['content'], ['bars'], ['bars', 'content'], ['content', 'bars']),
    )

    smooth_scroll_end    = NumericProperty(None, allownone=True)
    slow_device_support  = BooleanProperty(False)
    parallel_delegation  = BooleanProperty(True)
    delegate_to_outer    = BooleanProperty(True)

    _MOUSE_WHEEL_HORIZONTAL = {'scrollleft', 'scrollright'}
    _MOUSE_WHEEL_VERTICAL   = {'scrolldown', 'scrollup'}
    _MOUSE_WHEEL_DECREASE   = {'scrolldown', 'scrollleft'}
    _MOUSE_WHEEL_INCREASE   = {'scrollup', 'scrollright'}

    _viewport  = ObjectProperty(None, allownone=True)
    _bar_color = ListProperty([0, 0, 0, 0])

    def _set_viewport_size(self, instance, value):
        self.viewport_size = value

    def on__viewport(self, instance, value):
        if value:
            value.bind(size=self._set_viewport_size)
            self.viewport_size = value.size

    # ── ThorVG rendering objects ───────────────────────────────────────────
    # _clip_shape   : Shape rect == the visible ScrollView bounds (clipper)
    # _content_scene: Scene holding children; clipped + translated
    # _vbar_shape   : vertical scrollbar Shape
    # _hbar_shape   : horizontal scrollbar Shape
    # _scroll_offset: (tx, ty) tuple mirroring g_translate.xy in Kivy

    def __init__(self, **kwargs):
        self._touch = None
        self._nested_sv_active_touch = None
        self._trigger_update_from_scroll = Clock.create_trigger(
            self.update_from_scroll, -1
        )
        self._velocity_check_ev      = None
        self._position_check_ev      = None
        self._last_scroll_pos        = None
        self._stable_frames          = 0
        self._effect_x_start_width   = None
        self._effect_y_start_height  = None
        self._update_effect_bounds_ev = None
        self._bind_inactive_bar_color_ev = None

        # ThorVG objects — created once, never destroyed during lifetime
        self._clip_shape    = Shape()
        self._content_scene = Scene()
        self._vbar_shape    = Shape()
        self._hbar_shape    = Shape()
        self._scroll_offset = (0.0, 0.0)   # replaces g_translate.xy

        # Clip the content scene to our bounds
        self._content_scene.set_clip(self._clip_shape)

        super(ScrollView, self).__init__(**kwargs)

        self.register_event_type('on_scroll_start')
        self.register_event_type('on_scroll_move')
        self.register_event_type('on_scroll_stop')

        self.fbind('scroll_x', self._on_scroll_pos_changed)
        self.fbind('scroll_y', self._on_scroll_pos_changed)

        effect_cls = self.effect_cls
        if isinstance(effect_cls, str):
            effect_cls = Factory.get(effect_cls)
        if self.effect_x is None and effect_cls is not None:
            self.effect_x = effect_cls(target_widget=self._viewport)
        if self.effect_y is None and effect_cls is not None:
            self.effect_y = effect_cls(target_widget=self._viewport)

        fbind = self.fbind
        fbind('width',         self._update_effect_x_bounds)
        fbind('height',        self._update_effect_y_bounds)
        fbind('viewport_size', self._update_effect_bounds)
        fbind('_viewport',     self._update_effect_widget)
        fbind('scroll_x',      self._trigger_update_from_scroll)
        fbind('scroll_y',      self._trigger_update_from_scroll)
        fbind('pos',           self._trigger_update_from_scroll)
        fbind('size',          self._trigger_update_from_scroll)

        # bar color changes
        self.fbind('bar_color',          self._on_bar_color)
        self.fbind('bar_inactive_color', self._on_bar_color)
        self.fbind('_bar_color',         self._sync_bar_shapes)
        self.fbind('vbar',               self._sync_bar_shapes)
        self.fbind('hbar',               self._sync_bar_shapes)
        self.fbind('pos',                self._sync_bar_shapes)
        self.fbind('size',               self._sync_bar_shapes)

        self._trigger_update_from_scroll()
        self._update_effect_widget()
        self._update_effect_x_bounds()
        self._update_effect_y_bounds()

    # ── effect wiring (identical to Kivy) ─────────────────────────────────

    def on_effect_x(self, instance, value):
        if value:
            value.bind(scroll=self._update_effect_x)
            value.target_widget = self._viewport

    def on_effect_y(self, instance, value):
        if value:
            value.bind(scroll=self._update_effect_y)
            value.target_widget = self._viewport

    def on_effect_cls(self, instance, cls):
        if isinstance(cls, str):
            cls = Factory.get(cls)
        self.effect_x = cls(target_widget=self._viewport)
        self.effect_x.bind(scroll=self._update_effect_x)
        self.effect_y = cls(target_widget=self._viewport)
        self.effect_y.bind(scroll=self._update_effect_y)

    def _update_effect_widget(self, *args):
        if self.effect_x:
            self.effect_x.target_widget = self._viewport
        if self.effect_y:
            self.effect_y.target_widget = self._viewport

    def _update_effect_x_bounds(self, *args):
        if not self._viewport or not self.effect_x:
            return
        sw = self.width - self.viewport_size[0]
        self.effect_x.min = 0
        self.effect_x.max = min(0, sw)
        self.effect_x.value = sw * self.scroll_x

    def _update_effect_y_bounds(self, *args):
        if not self._viewport or not self.effect_y:
            return
        sh = self.height - self.viewport_size[1]
        self.effect_y.min = 0 if sh < 0 else sh
        self.effect_y.max = sh
        self.effect_y.value = self.effect_y.max * self.scroll_y

    def _update_effect_bounds(self, *args):
        self._update_effect_x_bounds()
        self._update_effect_y_bounds()

    def _update_effect_x(self, *args):
        vp = self._viewport
        if not vp or not self.effect_x:
            return
        if self.effect_x.is_manual:
            sw = self.width - self.viewport_size[0]
        else:
            sw = self.width - self.viewport_size[0]
        if sw < 1 and not (self.always_overscroll and self.do_scroll_x):
            return
        if sw != 0:
            self.scroll_x = min(1.0, max(0.0, self.effect_x.value / sw))
        self._trigger_update_from_scroll()

    def _update_effect_y(self, *args):
        vp = self._viewport
        if not vp or not self.effect_y:
            return
        sh = self.height - self.viewport_size[1]
        if sh < 1 and not (self.always_overscroll and self.do_scroll_y):
            return
        if sh != 0:
            self.scroll_y = min(1.0, max(0.0, self.effect_y.value / sh))
        self._trigger_update_from_scroll()

    # ── coordinate transforms  ─────────────────────────────────────────────
    # Replaces Kivy's g_translate / PushMatrix / PopMatrix approach.

    def to_local(self, x, y, **k):
        tx, ty = self._scroll_offset
        return x - tx, y - ty

    def to_parent(self, x, y, **k):
        tx, ty = self._scroll_offset
        return x + tx, y + ty

    def _apply_transform(self, m, pos=None):
        tx, ty = self._scroll_offset
        m.translate(tx, ty, 0)
        return super(ScrollView, self)._apply_transform(m, (0, 0))

    # ── scrollbar ThorVG shapes ────────────────────────────────────────────

    def _on_bar_color(self, *_):
        self._bar_color = self.bar_color

    def _sync_bar_shapes(self, *_):
        bw = self.bar_width
        bm = self.bar_margin
        r, g, b, a = (int(c * 255) for c in self._bar_color)

        # vertical bar
        vy, vh = self.vbar
        vbar_h = vh * self.height
        vbar_y = self.y + vy * self.height
        if self.bar_pos_y == 'right':
            vbar_x = self.right - bw - bm
        else:
            vbar_x = self.x + bm
        self._vbar_shape.reset()
        self._vbar_shape.append_rect(vbar_x, vbar_y, bw, vbar_h, 0, 0)
        self._vbar_shape.set_fill_color(r, g, b, a)

        # horizontal bar
        hx, hw = self.hbar
        hbar_w = hw * self.width
        hbar_x = self.x + hx * self.width
        if self.bar_pos_x == 'bottom':
            hbar_y = self.y + bm
        else:
            hbar_y = self.top - bw - bm
        self._hbar_shape.reset()
        self._hbar_shape.append_rect(hbar_x, hbar_y, hbar_w, bw, 0, 0)
        self._hbar_shape.set_fill_color(r, g, b, a)

    # ── simulate_touch_down (unchanged logic) ─────────────────────────────

    def _simulate_touch_down(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_local)
        ret = super(ScrollView, self).on_touch_down(touch)
        touch.pop()
        return ret

    # ── motion ────────────────────────────────────────────────────────────

    def on_motion(self, etype, me):
        if me.type_id in self.motion_filter and 'pos' in me.profile:
            local = self.to_local(*me.pos)
            me.push()
            me.pos = local
            r = super().on_motion(etype, me)
            me.pop()
            return r
        return super().on_motion(etype, me)

    # ── delegate helpers (unchanged logic) ────────────────────────────────

    def _delegate_to_children(self, touch, method_name, check_collision=True):
        if check_collision and not self.collide_point(*touch.pos):
            return False
        touch.push()
        touch.apply_transform_2d(self.to_local)
        res = getattr(super(ScrollView, self), method_name)(touch)
        touch.pop()
        return res

    def _delegate_touch_up_to_children_widget_coords(self, touch):
        touch.push()
        touch.apply_transform_2d(self.to_widget)
        res = super(ScrollView, self).on_touch_up(touch)
        touch.pop()
        return res

    # ── child widget finding (unchanged logic) ────────────────────────────

    def _find_child_scrollview_at_touch(self, touch):
        viewport = self._viewport
        if not viewport:
            return None
        if not hasattr(viewport, 'children'):
            return None
        if not viewport.children:
            return None
        touch.push()
        touch.apply_transform_2d(viewport.to_widget)
        result = self._find_scrollview_in_widget(viewport, touch)
        touch.pop()
        return result

    def _find_scrollview_in_widget(self, widget, touch):
        if hasattr(widget, 'children') and widget.children:
            for child in reversed(widget.children):
                if not child.collide_point(*touch.pos):
                    continue
                if isinstance(child, ScrollView):
                    return child
                result = self._find_scrollview_in_widget(child, touch)
                if result:
                    return result
        return None

    def _build_hierarchy_recursive(self, touch):
        child_sv = self._find_child_scrollview_at_touch(touch)
        if not child_sv:
            return None
        hierarchy = ScrollViewHierarchy(self)
        current_sv = child_sv
        parent_sv = self
        while current_sv:
            classification, axis_config = parent_sv._classify_nested_configuration(current_sv)
            hierarchy.add_child(current_sv, classification, axis_config)
            parent_sv = current_sv
            current_sv = current_sv._find_child_scrollview_at_touch(touch)
        return hierarchy

    def _get_nested_data(self, touch):
        if 'nested' not in touch.ud:
            return None, None, None
        if 'hierarchy' not in touch.ud['nested']:
            return None, None, None
        hierarchy = touch.ud['nested']['hierarchy']
        my_index = None
        for i, sv in enumerate(hierarchy.scrollviews):
            if sv is self:
                my_index = i
                break
        if my_index is None:
            return None, None, None
        return hierarchy, my_index, hierarchy.get_parent(my_index)

    def _get_primary_scroll_axis(self, touch):
        abs_dx = abs(touch.dx)
        abs_dy = abs(touch.dy)
        if abs_dx > abs_dy:
            return 'x'
        elif abs_dy > abs_dx:
            return 'y'
        return None

    def _classify_nested_configuration(self, child_sv):
        outer_axes = (self.do_scroll_x, self.do_scroll_y)
        inner_axes = (child_sv.do_scroll_x, child_sv.do_scroll_y)
        is_orthogonal = (
            outer_axes[0] != inner_axes[0]
            and outer_axes[1] != inner_axes[1]
            and (outer_axes[0] or outer_axes[1])
            and (inner_axes[0] or inner_axes[1])
        )
        if is_orthogonal:
            return ('orthogonal', None)
        if outer_axes == inner_axes:
            return ('parallel', None)
        shared = []
        outer_exclusive = []
        inner_exclusive = []
        if outer_axes[0] and inner_axes[0]:
            shared.append('x')
        elif outer_axes[0]:
            outer_exclusive.append('x')
        elif inner_axes[0]:
            inner_exclusive.append('x')
        if outer_axes[1] and inner_axes[1]:
            shared.append('y')
        elif outer_axes[1]:
            outer_exclusive.append('y')
        elif inner_axes[1]:
            inner_exclusive.append('y')
        return ('mixed', {'shared': shared, 'outer_exclusive': outer_exclusive,
                          'inner_exclusive': inner_exclusive})

    def _initialize_nested_inner(self, touch, child_sv):
        is_wheel = 'button' in touch.profile and touch.button.startswith('scroll')
        touch.push()
        touch.apply_transform_2d(child_sv.parent.to_widget)
        result = child_sv._scroll_initialize(touch)
        touch.pop()
        if result:
            return result
        if is_wheel:
            return self._scroll_initialize(touch)
        return False

    # ── touch helper stubs that delegate to Kivy ScrollView logic ─────────
    # All the complex nested-scroll state-machine methods are copied directly
    # from Kivy's ScrollView — they are pure Python with no canvas dependency.

    def _setup_boundary_delegation(self, touch, in_bar):
        pass  # filled in by mixin below

    def _delegate_to_parent_scroll(self, touch, child_sv, parent_sv):
        pass

    def _detect_scroll_intent(self, touch, ud):
        pass

    def _check_nested_delegation(self, touch, not_in_bar):
        pass

    def _is_at_scroll_boundary(self, axis):
        if axis == 'x':
            return isclose(self.scroll_x, 0.0, abs_tol=_BOUNDARY_THRESHOLD) or \
                   isclose(self.scroll_x, 1.0, abs_tol=_BOUNDARY_THRESHOLD)
        return isclose(self.scroll_y, 0.0, abs_tol=_BOUNDARY_THRESHOLD) or \
               isclose(self.scroll_y, 1.0, abs_tol=_BOUNDARY_THRESHOLD)

    def _is_scrolling_beyond_boundary(self, axis, touch):
        if axis == 'x':
            return (touch.dx < 0 and isclose(self.scroll_x, 1.0, abs_tol=_BOUNDARY_THRESHOLD)) or \
                   (touch.dx > 0 and isclose(self.scroll_x, 0.0, abs_tol=_BOUNDARY_THRESHOLD))
        return (touch.dy < 0 and isclose(self.scroll_y, 0.0, abs_tol=_BOUNDARY_THRESHOLD)) or \
               (touch.dy > 0 and isclose(self.scroll_y, 1.0, abs_tol=_BOUNDARY_THRESHOLD))

    def _find_parallel_ancestor(self, touch, axis):
        parent = self.parent
        while parent:
            if isinstance(parent, ScrollView):
                if axis == 'x' and parent.do_scroll_x:
                    return parent
                if axis == 'y' and parent.do_scroll_y:
                    return parent
            parent = getattr(parent, 'parent', None)
        return None

    def _handle_focus_behavior(self, touch, uid_key):
        pass

    def _touch_in_handle(self, pos, size, touch):
        x, y = pos
        w, h = size
        return x <= touch.x <= x + w and y <= touch.y <= y + h

    def _check_scroll_bounds(self, touch):
        pass

    def _handle_mouse_wheel_scroll(self, btn, in_bar_x, in_bar_y):
        pass

    def _select_scroll_effect_for_wheel(self, btn, in_bar_x, in_bar_y):
        pass

    def _apply_wheel_scroll(self, effect, btn, distance):
        pass

    def _handle_scrollbar_jump(self, touch, in_bar_x, in_bar_y):
        pass

    def _initialize_scroll_effects(self, touch, in_bar):
        pass

    def _should_delegate_orthogonal(self, touch, parent_sv):
        pass

    def _should_delegate_mixed(self, touch, parent_sv, axis_config):
        pass

    def _should_delegate_parallel(self, touch, parent_sv):
        pass

    def _process_scroll_axis_x(self, touch, not_in_bar):
        pass

    def _process_scroll_axis_y(self, touch, not_in_bar):
        pass

    def _stop_scroll_effects(self, touch, not_in_bar):
        pass

    def _finalize_scroll_for_cascade(self, touch):
        pass

    # ── main scroll / update ───────────────────────────────────────────────

    def update_from_scroll(self, *largs):
        if not self._viewport:
            # no content — reset clip to our bounds, offset to origin
            self._scroll_offset = (self.x, self.y)
            self._sync_clip_shape()
            self._content_scene.set_transform(TvgMatrix(
                e13=self.x, e23=self.y))
            return

        vp = self._viewport

        if vp.size_hint_x is not None:
            w = vp.size_hint_x * self.width
            if vp.size_hint_min_x is not None:
                w = max(w, vp.size_hint_min_x)
            if vp.size_hint_max_x is not None:
                w = min(w, vp.size_hint_max_x)
            vp.width = w

        if vp.size_hint_y is not None:
            h = vp.size_hint_y * self.height
            if vp.size_hint_min_y is not None:
                h = max(h, vp.size_hint_min_y)
            if vp.size_hint_max_y is not None:
                h = min(h, vp.size_hint_max_y)
            vp.height = h

        if vp.width > self.width or self.always_overscroll:
            sw = vp.width - self.width
            x = self.x - self.scroll_x * sw
        else:
            x = self.x

        if vp.height > self.height or self.always_overscroll:
            sh = vp.height - self.height
            y = self.y - self.scroll_y * sh
        else:
            y = self.top - vp.height

        vp.pos = 0, 0
        self._scroll_offset = (x, y)
        self._content_scene.set_transform(TvgMatrix(e13=x, e23=y))
        self._sync_clip_shape()

        # bar fade
        ev = self._bind_inactive_bar_color_ev
        if ev is None:
            ev = self._bind_inactive_bar_color_ev = Clock.create_trigger(
                self._bind_inactive_bar_color, 0.5)
        self.funbind('bar_inactive_color', self._change_bar_color)
        Animation.stop_all(self, '_bar_color')
        self.fbind('bar_color', self._change_bar_color)
        self._bar_color = self.bar_color
        ev()

    def _sync_clip_shape(self):
        self._clip_shape.reset()
        self._clip_shape.append_rect(
            float(self.x), float(self.y),
            float(self.width), float(self.height),
            0, 0)

    def _bind_inactive_bar_color(self, *args):
        self.funbind('bar_color', self._change_bar_color)
        self.fbind('bar_inactive_color', self._change_bar_color)
        Animation(_bar_color=self.bar_inactive_color, d=0.5, t='out_quart').start(self)

    def _change_bar_color(self, inst, value):
        self._bar_color = value

    # ── scroll_to / convert_distance_to_scroll ────────────────────────────

    def scroll_to(self, widget, padding=10, animate=True):
        if not self._viewport:
            return
        if widget is self._viewport or not self._viewport.is_ancestor(widget):
            return
        pos = widget.pos
        cor = self._viewport.to_widget(*widget.to_window(*pos))
        dx = dy = 0
        if cor[0] < self.x:
            dx = self.x - cor[0] + padding
        elif cor[0] + widget.width > self.right:
            dx = self.right - (cor[0] + widget.width) - padding
        if cor[1] < self.y:
            dy = self.y - cor[1] + padding
        elif cor[1] + widget.height > self.top:
            dy = self.top - (cor[1] + widget.height) - padding
        sdx, sdy = self.convert_distance_to_scroll(dx, dy)
        if animate:
            Animation(scroll_x=self.scroll_x - sdx,
                      scroll_y=self.scroll_y - sdy,
                      d=0.2, t='out_quart').start(self)
        else:
            self.scroll_x = min(1, max(0, self.scroll_x - sdx))
            self.scroll_y = min(1, max(0, self.scroll_y - sdy))

    def convert_distance_to_scroll(self, dx, dy):
        if not self._viewport:
            return 0, 0
        vp_w = self.viewport_size[0]
        vp_h = self.viewport_size[1]
        if vp_w == 0 or self.width == 0:
            sx = 0
        elif vp_w <= self.width:
            sx = 0
        else:
            sx = dx / float(vp_w - self.width)
        if vp_h == 0 or self.height == 0:
            sy = 0
        elif vp_h <= self.height:
            sy = 0
        else:
            sy = dy / float(vp_h - self.height)
        return sx, sy

    # ── add / remove child ─────────────────────────────────────────────────

    def add_widget(self, widget, *args, **kwargs):
        if self._viewport:
            raise Exception('ScrollView accepts only one child widget')
        # Standard widget tree add (position/size bookkeeping)
        super(ScrollView, self).add_widget(widget, *args, **kwargs)
        self._viewport = widget
        widget.bind(
            size=self._trigger_update_from_scroll,
            size_hint_min=self._trigger_update_from_scroll,
        )
        self._trigger_update_from_scroll()

    def remove_widget(self, widget, *args, **kwargs):
        super(ScrollView, self).remove_widget(widget, *args, **kwargs)
        if widget is self._viewport:
            self._viewport = None

    # ── scroll position changed ────────────────────────────────────────────

    def _on_scroll_pos_changed(self, instance, value):
        self.dispatch('on_scroll_move')

    def _check_position_stable(self, dt):
        current_pos = (self.scroll_x, self.scroll_y)
        if self._last_scroll_pos is None:
            self._last_scroll_pos = current_pos
            self._stable_frames = 0
        if isclose(current_pos[0], self._last_scroll_pos[0], abs_tol=1e-5) and \
           isclose(current_pos[1], self._last_scroll_pos[1], abs_tol=1e-5):
            self._stable_frames += 1
        else:
            self._stable_frames = 0
            self._last_scroll_pos = current_pos
        if self._stable_frames >= 3:
            self._position_check_ev = None
            self._last_scroll_pos = None
            self._stable_frames = 0
            self.dispatch('on_scroll_stop')
            return False

    def _check_velocity_for_stop(self, dt):
        ex = self.effect_x
        ey = self.effect_y
        vx = abs(ex.velocity) if ex else 0
        vy = abs(ey.velocity) if ey else 0
        if vx < 1 and vy < 1:
            if self._position_check_ev is None:
                self._position_check_ev = Clock.schedule_interval(
                    self._check_position_stable, 0)
            self._velocity_check_ev = None
            return False

    def _get_uid(self, prefix='sv'):
        return '{0}.{1}'.format(prefix, self.uid)

    def _get_debug_name(self):
        name = self.__class__.__name__
        if hasattr(self, 'id') and self.id:
            return '{}/{}'.format(name, self.id)
        return name

    # ── touch handling — copied verbatim from Kivy ScrollView ─────────────
    # These methods are pure Python (no canvas); we re-use them directly by
    # copy-pasting the bodies from the Kivy source via _kivy_sv below.

    def _change_touch_mode(self, *largs):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._change_touch_mode(self, *largs)

    def _do_touch_up(self, touch, *largs):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._do_touch_up(self, touch, *largs)

    def _scroll_initialize(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._scroll_initialize(self, touch)

    def _scroll_update(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._scroll_update(self, touch)

    def _scroll_finalize(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._scroll_finalize(self, touch)

    def on_touch_down(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV.on_touch_down(self, touch)

    def on_touch_move(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV.on_touch_move(self, touch)

    def on_touch_up(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV.on_touch_up(self, touch)

    def _setup_boundary_delegation(self, touch, in_bar):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._setup_boundary_delegation(self, touch, in_bar)

    def _delegate_to_parent_scroll(self, touch, child_sv, parent_sv):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._delegate_to_parent_scroll(self, touch, child_sv, parent_sv)

    def _detect_scroll_intent(self, touch, ud):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._detect_scroll_intent(self, touch, ud)

    def _check_nested_delegation(self, touch, not_in_bar):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._check_nested_delegation(self, touch, not_in_bar)

    def _handle_focus_behavior(self, touch, uid_key):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._handle_focus_behavior(self, touch, uid_key)

    def _check_scroll_bounds(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._check_scroll_bounds(self, touch)

    def _handle_mouse_wheel_scroll(self, btn, in_bar_x, in_bar_y):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._handle_mouse_wheel_scroll(self, btn, in_bar_x, in_bar_y)

    def _select_scroll_effect_for_wheel(self, btn, in_bar_x, in_bar_y):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._select_scroll_effect_for_wheel(self, btn, in_bar_x, in_bar_y)

    def _apply_wheel_scroll(self, effect, btn, distance):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._apply_wheel_scroll(self, effect, btn, distance)

    def _handle_scrollbar_jump(self, touch, in_bar_x, in_bar_y):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._handle_scrollbar_jump(self, touch, in_bar_x, in_bar_y)

    def _initialize_scroll_effects(self, touch, in_bar):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._initialize_scroll_effects(self, touch, in_bar)

    def _should_delegate_orthogonal(self, touch, parent_sv):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._should_delegate_orthogonal(self, touch, parent_sv)

    def _should_delegate_mixed(self, touch, parent_sv, axis_config):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._should_delegate_mixed(self, touch, parent_sv, axis_config)

    def _should_delegate_parallel(self, touch, parent_sv):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._should_delegate_parallel(self, touch, parent_sv)

    def _process_scroll_axis_x(self, touch, not_in_bar):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._process_scroll_axis_x(self, touch, not_in_bar)

    def _process_scroll_axis_y(self, touch, not_in_bar):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._process_scroll_axis_y(self, touch, not_in_bar)

    def _stop_scroll_effects(self, touch, not_in_bar):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._stop_scroll_effects(self, touch, not_in_bar)

    def _finalize_scroll_for_cascade(self, touch):
        from kivy.uix.scrollview import ScrollView as _KivySV
        return _KivySV._finalize_scroll_for_cascade(self, touch)

    # ── thor-canvas protocol ───────────────────────────────────────────────

    def canvas_init(self, canvas: GlCanvas):
        self._sync_clip_shape()
        self._sync_bar_shapes()
        canvas.add(self._content_scene)
        canvas.add(self._vbar_shape)
        canvas.add(self._hbar_shape)
        # propagate to child viewport
        if self._viewport and hasattr(self._viewport, 'canvas_init'):
            self._viewport.canvas_init(self._content_scene)

    def scene_init(self, scene: Scene):
        self._sync_clip_shape()
        self._sync_bar_shapes()
        scene.add(self._content_scene)
        scene.add(self._vbar_shape)
        scene.add(self._hbar_shape)
        if self._viewport and hasattr(self._viewport, 'scene_init'):
            self._viewport.scene_init(self._content_scene)

    def canvas_remove(self, canvas: GlCanvas):
        if self._viewport and hasattr(self._viewport, 'canvas_remove'):
            self._viewport.canvas_remove(self._content_scene)
        canvas.remove(self._content_scene)
        canvas.remove(self._vbar_shape)
        canvas.remove(self._hbar_shape)

    def scene_remove(self, scene: Scene):
        if self._viewport and hasattr(self._viewport, 'scene_remove'):
            self._viewport.scene_remove(self._content_scene)
        scene.remove(self._content_scene)
        scene.remove(self._vbar_shape)
        scene.remove(self._hbar_shape)

    def canvas_update(self, dt: float) -> bool:
        needs = False
        if self._viewport and hasattr(self._viewport, 'canvas_update'):
            if self._viewport.canvas_update(dt):
                needs = True
        return needs

    # ── events ────────────────────────────────────────────────────────────

    def on_scroll_start(self):
        pass

    def on_scroll_move(self):
        pass

    def on_scroll_stop(self):
        pass
