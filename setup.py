import os
import sys
from pathlib import Path

from setuptools import setup
from Cython.Build import cythonize
from Cython.Distutils import Extension
import kivy

# ---------------------------------------------------------------------------
#  thorvg_capi.h — not shipped in the thorvg-cython wheel, so the caller
#  must set THORVG_CAPI_INCLUDE to the directory that contains it.
#  (e.g. <workspace>/thorvg-cython/thorvg/src/bindings/capi)
# ---------------------------------------------------------------------------
THORVG_CAPI_INCLUDE = os.environ.get("THORVG_CAPI_INCLUDE", "")
if not THORVG_CAPI_INCLUDE:
    raise RuntimeError(
        "Set THORVG_CAPI_INCLUDE to the directory containing thorvg_capi.h"
    )

# ---------------------------------------------------------------------------
#  Compile flags
# ---------------------------------------------------------------------------
extra_compile_args = []
if sys.platform == "darwin":
    extra_compile_args.append(
        f"-mmacosx-version-min={os.environ.get('MACOSX_DEPLOYMENT_TARGET', '11.0')}"
    )

# ---------------------------------------------------------------------------
#  ANGLE / EGL — tfbo.pyx links against libEGL for eglGetCurrent* calls
# ---------------------------------------------------------------------------
ANGLE_INCLUDE_DIR = os.environ.get("ANGLE_INCLUDE_DIR", "")
ANGLE_LIB_DIR = os.environ.get("ANGLE_LIB_DIR", "")
tfbo_extra_link_args = []
tfbo_library_dirs = []
tfbo_include_dirs = [ANGLE_INCLUDE_DIR] if ANGLE_INCLUDE_DIR else []
if ANGLE_LIB_DIR:
    tfbo_library_dirs = [ANGLE_LIB_DIR]
    tfbo_extra_link_args = ["-lEGL"]
elif sys.platform == "darwin":
    # Fallback: try the libEGL bundled inside the installed kivy wheel
    _kivy_dylibs = os.path.join(os.path.dirname(kivy.__file__), ".dylibs")
    _egl = os.path.join(_kivy_dylibs, "libEGL.dylib")
    # Check for bundled ANGLE headers next to libs
    _kivy_deps_inc = os.path.join(
        os.path.dirname(kivy.__file__), "..", "kivy-dependencies", "dist", "include"
    )
    if os.path.exists(_egl):
        tfbo_library_dirs = [_kivy_dylibs]
        tfbo_extra_link_args = ["-lEGL"]
        if not tfbo_include_dirs and os.path.isdir(_kivy_deps_inc):
            tfbo_include_dirs = [_kivy_deps_inc]

# ---------------------------------------------------------------------------
#  Cython include path — needed for .pyx files to find .pxd declarations
#  (kivy/graphics/cgl.pxd, thorvg_cython/gl_canvas.pxd, etc.)
# ---------------------------------------------------------------------------
import thorvg_cython as _tvg
_site_packages = os.path.dirname(os.path.dirname(kivy.__file__))
_tvg_site = os.path.dirname(os.path.dirname(_tvg.__file__))
_cython_include_path = list({_site_packages, _tvg_site, "src"})

_c_include_dirs = kivy.get_includes() + [THORVG_CAPI_INCLUDE]

setup(
    ext_modules=cythonize(
        [
            # Extension(
            #     "kivy_thor.thorfbo",
            #     sources=["src/kivy_thor/thorfbo.py"],
            #     include_dirs=_c_include_dirs,
            #     extra_compile_args=extra_compile_args,
            # ),
            Extension(
                "kivy_thor.thor_fbo",
                sources=["src/kivy_thor/thor_fbo.pyx"],
                include_dirs=_c_include_dirs + tfbo_include_dirs,
                library_dirs=tfbo_library_dirs,
                extra_compile_args=extra_compile_args,
                extra_link_args=tfbo_extra_link_args,
            ),
            Extension(
                "kivy_thor.thorlayer",
                sources=["src/kivy_thor/thorlayer.pyx"],
                include_dirs=_c_include_dirs,
                extra_compile_args=extra_compile_args,
            ),
        ],
        include_path=_cython_include_path,
        compiler_directives={"language_level": "3"},
    ),
)
