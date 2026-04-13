__all__ = ('ToggleButton', )

from kivy.uix.behaviors import ToggleButtonBehavior

from kivy_thor.uix.button import Button


class ToggleButton(ToggleButtonBehavior, Button):
    pass
