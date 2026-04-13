__all__ = ('Layout', )

from kivy.clock import Clock
from kivy_thor.uix.widget import Widget
from math import isclose
from thorvg_cython import Scene, GlCanvas

class Layout(Widget):
    '''Layout interface class, used to implement every layout.'''

    _trigger_layout = None
    __scene: Scene

    def __init__(self, **kwargs):
        if self.__class__ == Layout:
            raise Exception('The Layout class is abstract and '
                            'cannot be used directly.')
        self.__scene = Scene()
        if self._trigger_layout is None:
            self._trigger_layout = Clock.create_trigger(self.do_layout, -1)
        super(Layout, self).__init__(**kwargs)

    def do_layout(self, *largs):
        raise NotImplementedError('Must be implemented in subclasses.')

    def add_widget(self, widget, *args, **kwargs):
        fbind = widget.fbind
        fbind('size', self._trigger_layout)
        fbind('size_hint', self._trigger_layout)
        fbind('size_hint_max', self._trigger_layout)
        fbind('size_hint_min', self._trigger_layout)
        super(Layout, self).add_widget(widget, *args, **kwargs)

    def remove_widget(self, widget, *args, **kwargs):
        funbind = widget.funbind
        funbind('size', self._trigger_layout)
        funbind('size_hint', self._trigger_layout)
        funbind('size_hint_max', self._trigger_layout)
        funbind('size_hint_min', self._trigger_layout)
        super(Layout, self).remove_widget(widget, *args, **kwargs)

    def layout_hint_with_bounds(
            self, sh_sum, available_space, min_bounded_size, sh_min_vals,
            sh_max_vals, hint):
        if not sh_sum:
            return

        stretch_ratio = sh_sum / float(available_space)
        if available_space <= min_bounded_size or \
                isclose(available_space, min_bounded_size):
            for i, (sh, sh_min) in enumerate(zip(hint, sh_min_vals)):
                if sh is None:
                    continue
                if sh_min is not None:
                    hint[i] = sh_min * stretch_ratio
                else:
                    hint[i] = 0.
            return

        not_mined_contrib = {}
        not_maxed_contrib = {}
        sh_mins_avail = {}
        sh_maxs_avail = {}
        oversize_amt = undersize_amt = 0
        hint_orig = hint[:]

        for i, (sh, sh_min, sh_max) in enumerate(
                zip(hint, sh_min_vals, sh_max_vals)):
            if sh is None:
                continue

            diff = 0

            if sh_min is not None:
                sh_min *= stretch_ratio
                diff = sh_min - sh

                if diff > 0:
                    hint[i] = sh_min
                    undersize_amt += diff
                else:
                    not_mined_contrib[i] = None

                sh_mins_avail[i] = hint[i] - sh_min
            else:
                not_mined_contrib[i] = None
                sh_mins_avail[i] = hint[i]

            if sh_max is not None:
                sh_max *= stretch_ratio
                diff = sh - sh_max

                if diff > 0:
                    hint[i] = sh_max
                    oversize_amt += diff
                else:
                    not_maxed_contrib[i] = None

                sh_maxs_avail[i] = sh_max - hint[i]
            else:
                not_maxed_contrib[i] = None
                sh_maxs_avail[i] = sh_sum - hint[i]

            if i in not_mined_contrib:
                not_mined_contrib[i] = max(0., diff)
            if i in not_maxed_contrib:
                not_maxed_contrib[i] = max(0., diff)

        margin = oversize_amt - undersize_amt
        if isclose(oversize_amt, undersize_amt, abs_tol=1e-15):
            return

        if margin > 1e-15:
            contrib_amt = not_maxed_contrib
            sh_available = sh_maxs_avail
            mult = 1.
            contrib_proportion = hint_orig
        elif margin < -1e-15:
            margin *= -1.
            contrib_amt = not_mined_contrib
            sh_available = sh_mins_avail
            mult = -1.

            mn = min((h for h in hint_orig if h))
            mx = max((h for h in hint_orig if h is not None))
            hint_top = (2. * mn if mn else 1.) if mn == mx else mn + mx
            contrib_proportion = [None if h is None else hint_top - h for
                                  h in hint_orig]

        contrib_prop_sum = float(
            sum((contrib_proportion[i] for i in contrib_amt)))

        if contrib_prop_sum < 1e-9:
            assert mult == 1.
            return

        contrib_height = {
            i: val / (contrib_proportion[i] / contrib_prop_sum) for
            i, val in contrib_amt.items()}
        items = sorted(
            (i for i in contrib_amt),
            key=lambda x: contrib_height[x])

        j = items[0]
        sum_i_contributed = contrib_amt[j]
        last_height = contrib_height[j]
        sh_available_i = {j: sh_available[j]}
        contrib_prop_sum_i = contrib_proportion[j]

        n = len(items)
        i = 1
        if 1 < n:
            j = items[1]
            curr_height = contrib_height[j]

        done = False
        while not done and i < n:
            while i < n and last_height == curr_height:
                j = items[i]
                sum_i_contributed += contrib_amt[j]
                contrib_prop_sum_i += contrib_proportion[j]
                sh_available_i[j] = sh_available[j]
                curr_height = contrib_height[j]
                i += 1
            last_height = curr_height

            while not done:
                margin_height = ((margin + sum_i_contributed) /
                                 (contrib_prop_sum_i / contrib_prop_sum))
                if margin_height - curr_height > 1e-9 and i < n:
                    break

                done = True
                for k, available_sh in list(sh_available_i.items()):
                    if margin_height - available_sh / (
                            contrib_proportion[k] / contrib_prop_sum) > 1e-9:
                        del sh_available_i[k]
                        sum_i_contributed -= contrib_amt[k]
                        contrib_prop_sum_i -= contrib_proportion[k]
                        margin -= available_sh
                        hint[k] += mult * available_sh
                        done = False

                if not sh_available_i:
                    break

        if sh_available_i:
            assert contrib_prop_sum_i and margin
            margin_height = ((margin + sum_i_contributed) /
                             (contrib_prop_sum_i / contrib_prop_sum))
            for i in sh_available_i:
                hint[i] += mult * (
                    margin_height * contrib_proportion[i] / contrib_prop_sum -
                    contrib_amt[i])

    def canvas_init(self, canvas: GlCanvas):
        s = self.__scene
        canvas.add(s)
        for c in self.children:
            c.scene_init(s)

    def scene_init(self, scene):
        s = self.__scene
        scene.add(s)
        for c in self.children:
            c.scene_init(s)

    def canvas_remove(self, canvas):
        s = self.__scene
        canvas.remove(s)
    
    def scene_remove(self, scene):
        s = self.__scene
        scene.remove(s)