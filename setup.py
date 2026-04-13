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

setup(
    ext_modules=cythonize(
        [
            Extension(
                "kivy_thor.thorfbo",
                sources=["src/kivy_thor/thorfbo.py"],
                include_dirs=kivy.get_includes() + [THORVG_CAPI_INCLUDE],
                extra_compile_args=extra_compile_args,
            ),
        ],
        compiler_directives={"language_level": "3"},
    ),
)
