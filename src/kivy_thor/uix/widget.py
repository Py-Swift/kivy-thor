__all__ = ('Widget', 'WidgetException', 'ThorWidget')

from kivy.event import EventDispatcher
from kivy.eventmanager import (
    MODE_DONT_DISPATCH,
    MODE_FILTERED_DISPATCH,
    MODE_DEFAULT_DISPATCH
)
from kivy.factory import Factory
from kivy.properties import (
    NumericProperty, AliasProperty, ReferenceListProperty,
    ObjectProperty, ListProperty, DictProperty)
from kivy.graphics.transformation import Matrix
from kivy.base import EventLoop
from kivy.lang import Builder
from kivy.context import get_current_context
from kivy.weakproxy import WeakProxy
from functools import partial
from itertools import islice

from thorvg_cython import GlCanvas, Scene


_widget_destructors = {}


def _widget_destructor(uid, r):
    del _widget_destructors[uid]
    Builder.unbind_widget(uid)


class WidgetException(Exception):
    pass


ThorWidgetException = WidgetException  # backwards-compat alias


class ThorWidgetMetaclass(type):
    def __init__(mcs, name, bases, attrs):
        super(ThorWidgetMetaclass, mcs).__init__(name, bases, attrs)
        Factory.register(name, cls=mcs)


ThorWidgetBase = ThorWidgetMetaclass('ThorWidgetBase', (EventDispatcher, ), {})


class Widget(ThorWidgetBase):

    __metaclass__ = ThorWidgetMetaclass
    __events__ = (
        'on_motion', 'on_touch_down', 'on_touch_move', 'on_touch_up',
        'on_kv_post'
    )
    _proxy_ref = None

    def __init__(self, **kwargs):
        EventLoop.ensure_window()

        if not hasattr(self, '_context'):
            self._context = get_current_context()

        no_builder = '__no_builder' in kwargs
        self._disabled_value = False
        if no_builder:
            del kwargs['__no_builder']
        on_args = {k: v for k, v in kwargs.items() if k[:3] == 'on_'}
        for key in on_args:
            del kwargs[key]

        self._disabled_count = 0

        super(ThorWidget, self).__init__(**kwargs)

        if not no_builder:
            rule_children = []
            self.apply_class_lang_rules(
                ignored_consts=self._kwargs_applied_init,
                rule_children=rule_children)

            for widget in rule_children:
                widget.dispatch('on_kv_post', self)
            self.dispatch('on_kv_post', self)

        if on_args:
            self.bind(**on_args)

    @property
    def proxy_ref(self):
        _proxy_ref = self._proxy_ref
        if _proxy_ref is not None:
            return _proxy_ref

        f = partial(_widget_destructor, self.uid)
        self._proxy_ref = _proxy_ref = WeakProxy(self, f)
        _widget_destructors[self.uid] = (f, _proxy_ref)
        return _proxy_ref

    def __hash__(self):
        return id(self)

    def apply_class_lang_rules(
            self, root=None, ignored_consts=set(), rule_children=None):
        Builder.apply(
            self, ignored_consts=ignored_consts,
            rule_children=rule_children)

    def collide_point(self, x, y):
        return self.x <= x <= self.right and self.y <= y <= self.top

    def collide_widget(self, wid):
        if self.right < wid.x:
            return False
        if self.x > wid.right:
            return False
        if self.top < wid.y:
            return False
        if self.y > wid.top:
            return False
        return True

    def on_motion(self, etype, me):
        if self.disabled or me.dispatch_mode == MODE_DONT_DISPATCH:
            return
        if me.type_id not in self.motion_filter:
            return
        filtered = self.motion_filter[me.type_id]
        if filtered[0] is self and len(filtered) == 1:
            return
        if me.dispatch_mode == MODE_DEFAULT_DISPATCH:
            last_filtered = filtered[-1]
            for widget in self.children[:]:
                if widget.dispatch('on_motion', etype, me):
                    return True
                if widget is last_filtered:
                    return
        if me.dispatch_mode == MODE_FILTERED_DISPATCH:
            widgets = filtered[1:] if filtered[0] is self else filtered[:]
            for widget in widgets:
                if widget.dispatch('on_motion', etype, me):
                    return True

    def on_touch_down(self, touch):
        if self.disabled and self.collide_point(*touch.pos):
            return True
        for child in self.children[:]:
            if child.dispatch('on_touch_down', touch):
                return True

    def on_touch_move(self, touch):
        if self.disabled:
            return
        for child in self.children[:]:
            if child.dispatch('on_touch_move', touch):
                return True

    def on_touch_up(self, touch):
        if self.disabled:
            return
        for child in self.children[:]:
            if child.dispatch('on_touch_up', touch):
                return True

    def on_kv_post(self, base_widget):
        pass

    def add_widget(self, widget, index=0, canvas=None):
        if not isinstance(widget, Widget):
            raise WidgetException(
                'add_widget() can be used only with instances'
                ' of the Widget class.')

        widget = widget.__self__
        if widget is self:
            raise WidgetException(
                'Widget instances cannot be added to themselves.')
        parent = widget.parent
        if parent:
            raise WidgetException(
                'Cannot add %r, it already has a parent %r'
                % (widget, parent))
        widget.parent = self
        widget.inc_disabled(self._disabled_count)

        if index == 0 or len(self.children) == 0:
            self.children.insert(0, widget)
        else:
            children = self.children
            if index >= len(children):
                index = len(children)
            children.insert(index, widget)

        for type_id in widget.motion_filter:
            self.register_for_motion_event(type_id, widget)
        widget.fbind('motion_filter', self._update_motion_filter)

    def remove_widget(self, widget):
        if widget not in self.children:
            return
        self.children.remove(widget)
        for type_id in widget.motion_filter:
            self.unregister_for_motion_event(type_id, widget)
        widget.funbind('motion_filter', self._update_motion_filter)
        widget.parent = None
        widget.dec_disabled(self._disabled_count)

    def clear_widgets(self, children=None):
        if children is None or children is self.children:
            children = self.children[:]
        remove_widget = self.remove_widget
        for child in children:
            remove_widget(child)

    def _update_motion_filter(self, child_widget, child_motion_filter):
        old_events = []
        for type_id, widgets in self.motion_filter.items():
            if child_widget in widgets:
                old_events.append(type_id)
        for type_id in old_events:
            if type_id not in child_motion_filter:
                self.unregister_for_motion_event(type_id, child_widget)
        for type_id in child_motion_filter:
            if type_id not in old_events:
                self.register_for_motion_event(type_id, child_widget)

    def _find_index_in_motion_filter(self, type_id, widget):
        if widget is self:
            return 0
        find_index = self.children.index
        max_index = find_index(widget) + 1
        motion_widgets = self.motion_filter[type_id]
        insert_index = 1 if motion_widgets[0] is self else 0
        for index in range(insert_index, len(motion_widgets)):
            if find_index(motion_widgets[index]) < max_index:
                insert_index += 1
            else:
                break
        return insert_index

    def register_for_motion_event(self, type_id, widget=None):
        a_widget = widget or self
        motion_filter = self.motion_filter
        if type_id not in motion_filter:
            motion_filter[type_id] = [a_widget]
        elif widget not in motion_filter[type_id]:
            index = self._find_index_in_motion_filter(type_id, a_widget)
            motion_filter[type_id].insert(index, a_widget)

    def unregister_for_motion_event(self, type_id, widget=None):
        a_widget = widget or self
        motion_filter = self.motion_filter
        if type_id in motion_filter:
            if a_widget in motion_filter[type_id]:
                motion_filter[type_id].remove(a_widget)
                if not motion_filter[type_id]:
                    del motion_filter[type_id]

    def get_root_window(self):
        if self.parent:
            return self.parent.get_root_window()

    def get_parent_window(self):
        if self.parent:
            return self.parent.get_parent_window()

    def _walk(self, restrict=False, loopback=False, index=None):
        if index is None:
            index = len(self.children)
            yield self

        for child in reversed(self.children[:index]):
            for walk_child in child._walk(restrict=True):
                yield walk_child

        if not restrict:
            parent = self.parent
            try:
                if parent is None or not isinstance(parent, Widget):
                    raise ValueError
                index = parent.children.index(self)
            except ValueError:
                if not loopback:
                    return
                parent = self
                index = None
            for walk_child in parent._walk(loopback=loopback, index=index):
                yield walk_child

    def walk(self, restrict=False, loopback=False):
        gen = self._walk(restrict, loopback)
        yield next(gen)
        for node in gen:
            if node is self:
                return
            yield node

    def _walk_reverse(self, loopback=False, go_up=False):
        root = self
        index = 0
        if go_up:
            root = self.parent
            try:
                if root is None or not isinstance(root, Widget):
                    raise ValueError
                index = root.children.index(self) + 1
            except ValueError:
                if not loopback:
                    return
                index = 0
                go_up = False
                root = self

        for child in islice(root.children, index, None):
            for walk_child in child._walk_reverse(loopback=loopback):
                yield walk_child
        yield root

        if go_up:
            for walk_child in root._walk_reverse(loopback=loopback,
                                                 go_up=go_up):
                yield walk_child

    def walk_reverse(self, loopback=False):
        for node in self._walk_reverse(loopback=loopback, go_up=True):
            yield node
            if node is self:
                return

    def to_widget(self, x, y, relative=False):
        if self.parent:
            x, y = self.parent.to_widget(x, y)
        return self.to_local(x, y, relative=relative)

    def to_window(self, x, y, initial=True, relative=False):
        if not initial:
            x, y = self.to_parent(x, y, relative=relative)
        if self.parent:
            return self.parent.to_window(x, y, initial=False,
                                         relative=relative)
        return (x, y)

    def to_parent(self, x, y, relative=False):
        if relative:
            return (x + self.x, y + self.y)
        return (x, y)

    def to_local(self, x, y, relative=False):
        if relative:
            return (x - self.x, y - self.y)
        return (x, y)

    def _apply_transform(self, m, pos=None):
        if self.parent:
            x, y = self.parent.to_widget(relative=True,
                                         *self.to_window(*(pos or self.pos)))
            m.translate(x, y, 0)
            m = self.parent._apply_transform(m) if self.parent else m
        return m

    def get_window_matrix(self, x=0, y=0):
        m = Matrix()
        m.translate(x, y, 0)
        m = self._apply_transform(m)
        return m

    x = NumericProperty(0)
    y = NumericProperty(0)
    width = NumericProperty(100)
    height = NumericProperty(100)

    pos = ReferenceListProperty(x, y)
    size = ReferenceListProperty(width, height)

    def get_right(self):
        return self.x + self.width

    def set_right(self, value):
        self.x = value - self.width

    right = AliasProperty(get_right, set_right,
                          bind=('x', 'width'),
                          cache=True, watch_before_use=False)

    def get_top(self):
        return self.y + self.height

    def set_top(self, value):
        self.y = value - self.height

    top = AliasProperty(get_top, set_top,
                        bind=('y', 'height'),
                        cache=True, watch_before_use=False)

    def get_center_x(self):
        return self.x + self.width / 2.

    def set_center_x(self, value):
        self.x = value - self.width / 2.

    center_x = AliasProperty(get_center_x, set_center_x,
                             bind=('x', 'width'),
                             cache=True, watch_before_use=False)

    def get_center_y(self):
        return self.y + self.height / 2.

    def set_center_y(self, value):
        self.y = value - self.height / 2.

    center_y = AliasProperty(get_center_y, set_center_y,
                             bind=('y', 'height'),
                             cache=True, watch_before_use=False)

    center = ReferenceListProperty(center_x, center_y)

    cls = ListProperty([])
    children = ListProperty([]) #type: list[Widget]
    parent = ObjectProperty(None, allownone=True, rebind=True)

    size_hint_x = NumericProperty(1, allownone=True)
    size_hint_y = NumericProperty(1, allownone=True)
    size_hint = ReferenceListProperty(size_hint_x, size_hint_y)

    pos_hint = ObjectProperty({})

    size_hint_min_x = NumericProperty(None, allownone=True)
    size_hint_min_y = NumericProperty(None, allownone=True)
    size_hint_min = ReferenceListProperty(size_hint_min_x, size_hint_min_y)

    size_hint_max_x = NumericProperty(None, allownone=True)
    size_hint_max_y = NumericProperty(None, allownone=True)
    size_hint_max = ReferenceListProperty(size_hint_max_x, size_hint_max_y)

    ids = DictProperty({})

    opacity = NumericProperty(1.0)

    def on_opacity(self, instance, value):
        if self.thor_canvas is not None:
            self.thor_canvas.opacity = value

    thor_canvas = None

    def get_disabled(self):
        return self._disabled_count > 0

    def set_disabled(self, value):
        value = bool(value)
        if value != self._disabled_value:
            self._disabled_value = value
            if value:
                self.inc_disabled()
            else:
                self.dec_disabled()

    def inc_disabled(self, count=1):
        self._disabled_count += count
        if self._disabled_count - count < 1 <= self._disabled_count:
            self.property('disabled').dispatch(self)
        for c in self.children:
            c.inc_disabled(count)

    def dec_disabled(self, count=1):
        self._disabled_count -= count
        if self._disabled_count <= 0 < self._disabled_count + count:
            self.property('disabled').dispatch(self)
        for c in self.children:
            c.dec_disabled(count)

    disabled = AliasProperty(get_disabled, set_disabled, watch_before_use=False)

    motion_filter = DictProperty()

    def canvas_init(self, canvas: GlCanvas):
        pass

    def scene_init(self, scene: Scene):
        pass

    def canvas_remove(self, canvas: GlCanvas):
        pass

    def scene_remove(self, scene: Scene):
        pass

    def canvas_update(self, dt: float) -> bool:
        needs_update = False
        for c in self.children:
            if c.canvas_update(dt):
                needs_update = True
        return needs_update

ThorWidget = Widget  # alias for users who prefer the explicit name
