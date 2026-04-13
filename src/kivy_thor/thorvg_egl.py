from os.path import join, dirname, exists
import os
import kivy 

def thorvg_load_egl(platform: str):
    if platform == "darwin":
        _dylibs = join(dirname(kivy.__file__), ".dylibs")
        _gles = join(_dylibs, "libGLESv2.dylib")
        _egl = join(_dylibs, "libEGL.dylib")
        if exists(_gles):
            os.environ.setdefault("THORVG_LIBGLESV2", _gles)
            print(f"[ThorFbo] THORVG_LIBGLESV2={_gles}")
        if exists(_egl):
            os.environ.setdefault("THORVG_LIBEGL", _egl)
            print(f"[ThorFbo] THORVG_LIBEGL={_egl}")
