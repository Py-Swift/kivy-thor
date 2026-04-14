#!/usr/bin/env python3
"""Build wheels for Kivy, thorvg-cython (GPU/ANGLE), and kivy-thor.

Run from a directory containing the sibling repos:
    cd <root>              ← has kivy/, thorvg-cython/, kivy-thor/
    python kivy-thor/scripts/build_kt.py all macos

Expected layout at CWD:
    kivy/               ← Kivy source
    thorvg-cython/      ← thorvg-cython source
    kivy-thor/          ← this repo
    wheelhouse/         ← created automatically for output wheels
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


THIS_FILE = Path(__file__).resolve()


# ── Platform ──────────────────────────────────────────────────────────────────

class Platform(Enum):
    MACOS   = "macos"
    IOS     = "ios"
    # LINUX   = "linux"     # future
    # WINDOWS = "windows"   # future


# ── Paths ─────────────────────────────────────────────────────────────────────

@dataclass
class Paths:
    """All configurable paths.  Resolved once from CLI args / env vars."""
    wheelhouse:          Path
    kivy_src:            Path
    thorvg_cython_src:   Path
    kivy_thor_src:       Path
    kivy_deps:           Path
    ios_kivy_deps:       Path
    angle_lib_dir:       Path
    angle_include_dir:   Path
    thorvg_capi_include: Path

    @property
    def repair_library_path(self) -> Path:
        return self.kivy_deps / "dist" / "Frameworks"


# Build settings
PYTHON_VERSION = "cp313-*"
IOS_ARCHS      = "arm64_iphoneos arm64_iphonesimulator x86_64_iphonesimulator"


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def run(cmd: list[str | Path], *, env: dict | None = None, cwd: Path | None = None) -> None:
    merged = {**os.environ, **(env or {})}
    merged = {k: str(v) for k, v in merged.items()}
    subprocess.run([str(c) for c in cmd], check=True, env=merged, cwd=cwd)


def capture(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def sdkroot(platform: Platform) -> str:
    sdk = "macosx" if platform is Platform.MACOS else "iphoneos"
    return capture(["xcrun", "--sdk", sdk, "--show-sdk-path"])


def xcode_toolchain_bin() -> str:
    return str(Path(capture(["xcrun", "-f", "clang"])).parent)


def _cibuildwheel(
    source: Path,
    platform: Platform,
    paths: Paths,
    *,
    env: dict | None = None,
    archs: str | None = None,
) -> None:
    cmd: list[str | Path] = ["cibuildwheel", "--platform", platform.value]
    if archs:
        cmd += ["--archs", archs]
    cmd += ["--output-dir", paths.wheelhouse, source]
    base: dict[str, str] = {
        "CIBW_BUILD": PYTHON_VERSION,
        "SDKROOT": sdkroot(platform),
    }
    base.update(env or {})
    run(cmd, env=base)


# ── Base builder ──────────────────────────────────────────────────────────────

class Builder:
    name: str
    wheel_prefix: str  # e.g. "Kivy-" or "thorvg_cython-"

    def __init__(self, paths: Paths) -> None:
        self.p = paths

    def _has_wheel(self, platform: Platform) -> bool:
        """True if a matching wheel already exists in the wheelhouse."""
        tag = "macosx" if platform is Platform.MACOS else "ios"
        return any(self.p.wheelhouse.glob(f"{self.wheel_prefix}*{tag}*.whl"))

    def build(self, platform: Platform | str) -> None:
        if isinstance(platform, str):
            platform = Platform(platform)
        self.p.wheelhouse.mkdir(parents=True, exist_ok=True)
        if platform is Platform.MACOS:
            self.build_macos()
        elif platform is Platform.IOS:
            self.build_ios()
        else:
            raise NotImplementedError(f"{platform.value} not yet supported")

    def build_macos(self) -> None:
        raise NotImplementedError

    def build_ios(self) -> None:
        raise NotImplementedError


# ── Kivy ──────────────────────────────────────────────────────────────────────

class Kivy(Builder):
    name = "kivy"
    wheel_prefix = "kivy-"

    def build_macos(self) -> None:
        if self._has_wheel(Platform.MACOS):
            log("Kivy macOS wheel already exists, skipping (delete it to rebuild).")
            return
        log("Building Kivy macOS dependencies...")
        run(["bash", "./tools/build_macos_dependencies.sh"], cwd=self.p.kivy_src)

        log("Building Kivy macOS wheel...")
        repair_path = self.p.repair_library_path
        repair = (
            f"DYLD_LIBRARY_PATH={repair_path} "
            "delocate-listdeps {wheel} && "
            f"DYLD_LIBRARY_PATH={repair_path} "
            "delocate-wheel --require-archs {delocate_archs} -w {dest_dir} {wheel}"
        )
        _cibuildwheel(self.p.kivy_src, Platform.MACOS, self.p, env={
            "USE_SDL3": "1",
            "KIVY_DEPS_ROOT": str(self.p.kivy_deps),
            "REPAIR_LIBRARY_PATH": str(repair_path),
            "CIBW_ENVIRONMENT": "MACOSX_DEPLOYMENT_TARGET=10.15",
            "CIBW_REPAIR_WHEEL_COMMAND_MACOS": repair,
        })
        log("Kivy macOS done.")

    def build_ios(self) -> None:
        if self._has_wheel(Platform.IOS):
            log("Kivy iOS wheels already exist, skipping (delete them to rebuild).")
            return
        log("Building Kivy iOS dependencies...")
        run(["bash", "./tools/build_ios_dependencies.sh"], cwd=self.p.kivy_src)

        log("Building Kivy iOS wheels...")
        _cibuildwheel(self.p.kivy_src, Platform.IOS, self.p, archs=IOS_ARCHS, env={
            "USE_SDL3": "1",
            "KIVY_DEPS_ROOT": str(self.p.ios_kivy_deps),
        })

        log("Patching Kivy iOS wheels with xcframeworks...")
        run(["python3", self.p.kivy_src / "tools" / "add-ios-frameworks.py",
             self.p.wheelhouse])
        log("Kivy iOS done.")


# ── ThorGPU ───────────────────────────────────────────────────────────────────

class ThorGPU(Builder):
    name = "thorgpu"
    wheel_prefix = "thorvg_cython-"

    THORVG_VERSION = "1.0.3"

    def build_macos(self) -> None:
        if self._has_wheel(Platform.MACOS):
            log("thorvg-cython macOS wheel already exists, skipping (delete it to rebuild).")
            return
        log("Building thorvg-cython macOS wheel (GPU/ANGLE)...")
        toolchain = xcode_toolchain_bin()

        tc = self.p.thorvg_cython_src
        before_all = (
            f"export PATH={toolchain}:$PATH && "
            f"python3 {tc}/tools/build_thorvg.py macos "
            f"--thorvg-root={tc}/thorvg "
            f"--version={self.THORVG_VERSION} --gpu=angle"
        )
        before_build = (
            "install_name_tool -id @rpath/libthorvg-1.dylib "
            f"{tc}/thorvg/output/macos_fat/libthorvg-1.dylib"
        )
        repair = (
            "delocate-wheel --require-archs {delocate_archs} "
            "-w {dest_dir} -v {wheel} && "
            f"python3 {THIS_FILE} _repair-thorgpu-wheel {{dest_dir}}"
        )
        cibw_env = " ".join([
            "THORVG_GPU=angle",
            f"THORVG_VERSION={self.THORVG_VERSION}",
            "THORVG_ROOT=thorvg",
            "THORVG_LIB_DIR=thorvg/output/macos_fat",
            f"ANGLE_LIB_DIR={self.p.angle_lib_dir}",
            "MACOSX_DEPLOYMENT_TARGET=11.0",
            f"PATH={toolchain}:$PATH",
        ])
        _cibuildwheel(self.p.thorvg_cython_src, Platform.MACOS, self.p, env={
            "THORVG_GPU": "angle",
            "CIBW_BEFORE_ALL_MACOS": before_all,
            "CIBW_BEFORE_BUILD_MACOS": before_build,
            "CIBW_REPAIR_WHEEL_COMMAND_MACOS": repair,
            "CIBW_TEST_COMMAND": "",
            "CIBW_ENVIRONMENT_MACOS": cibw_env,
        })
        log("thorvg-cython macOS done.")

    def build_ios(self) -> None:
        if self._has_wheel(Platform.IOS):
            log("thorvg-cython iOS wheels already exist, skipping (delete them to rebuild).")
            return
        log("Building thorvg-cython iOS wheels...")
        _cibuildwheel(self.p.thorvg_cython_src, Platform.IOS, self.p, archs=IOS_ARCHS, env={
            "THORVG_GPU": "angle",
        })

        log("Injecting xcframeworks into thorvg-cython iOS wheels...")
        tvg_output = self.p.thorvg_cython_src / "thorvg" / "output"
        run([
            "python3", self.p.thorvg_cython_src / "tools" / "add-ios-frameworks.py",
            self.p.wheelhouse,
            "--xcframework", tvg_output / "thorvg.xcframework",
            "--xcframework", tvg_output / "libomp.xcframework",
        ])
        log("thorvg-cython iOS done.")

    @staticmethod
    def repair_wheel(dest_dir: str) -> None:
        """Remove duplicate libthorvg-1.1.dylib from the repaired wheel."""
        import zipfile
        whl_name = next(p for p in os.listdir(dest_dir) if p.endswith(".whl"))
        src = os.path.join(dest_dir, whl_name)
        tmp = src + ".tmp"
        with zipfile.ZipFile(src, "r") as zin, zipfile.ZipFile(tmp, "w") as zout:
            for item in zin.infolist():
                if "libthorvg-1.1.dylib" in item.filename:
                    print(f"  Removing {item.filename}")
                    continue
                zout.writestr(item, zin.read(item.filename))
        os.replace(tmp, src)


# ── KivyThor ─────────────────────────────────────────────────────────────────

class KivyThor(Builder):
    name = "kivythor"
    wheel_prefix = "kivy_thor-"

    def build_macos(self) -> None:
        log("Building kivy-thor macOS wheel...")
        cibw_env = " ".join([
            "MACOSX_DEPLOYMENT_TARGET=11.0",
            f"PIP_FIND_LINKS={self.p.wheelhouse}",
            f"THORVG_CAPI_INCLUDE={self.p.thorvg_capi_include}",
            f"ANGLE_LIB_DIR={self.p.angle_lib_dir}",
            f"ANGLE_INCLUDE_DIR={self.p.angle_include_dir}",
        ])
        repair = (
            f"DYLD_LIBRARY_PATH={self.p.angle_lib_dir} "
            "delocate-listdeps {wheel} && "
            f"DYLD_LIBRARY_PATH={self.p.angle_lib_dir} "
            "delocate-wheel --require-archs {delocate_archs} "
            "--exclude libEGL --exclude libGLESv2 "
            "-w {dest_dir} {wheel}"
        )
        _cibuildwheel(self.p.kivy_thor_src, Platform.MACOS, self.p, env={
            "PIP_FIND_LINKS": str(self.p.wheelhouse),
            "CIBW_ENVIRONMENT_MACOS": cibw_env,
            "CIBW_REPAIR_WHEEL_COMMAND_MACOS": repair,
        })
        log("kivy-thor macOS done.")

    def build_ios(self) -> None:
        log("Building kivy-thor iOS wheels...")
        cibw_env = " ".join([
            f"PIP_FIND_LINKS={self.p.wheelhouse}",
            f"THORVG_CAPI_INCLUDE={self.p.thorvg_capi_include}",
            f"ANGLE_LIB_DIR={self.p.angle_lib_dir}",
            f"ANGLE_INCLUDE_DIR={self.p.angle_include_dir}",
        ])
        _cibuildwheel(self.p.kivy_thor_src, Platform.IOS, self.p, archs=IOS_ARCHS, env={
            "PIP_FIND_LINKS": str(self.p.wheelhouse),
            "CIBW_ENVIRONMENT_IOS": cibw_env,
        })
        log("kivy-thor iOS done.")


# ── Registry & build order ────────────────────────────────────────────────────

BUILDERS: dict[str, type[Builder]] = {
    "kivy":     Kivy,
    "thorgpu":  ThorGPU,
    "kivythor": KivyThor,
}

BUILD_ORDER = ["kivy", "thorgpu", "kivythor"]


# ── CLI ───────────────────────────────────────────────────────────────────────

REPOS = {
    "kivy":          "https://github.com/kivy/kivy",
    "thorvg-cython": "https://github.com/psychowasp/thorvg-cython.git",
}


def _clone_if_missing(dest: Path, url: str) -> None:
    if not dest.exists():
        log(f"Cloning {url} into {dest}")
        subprocess.run(["git", "clone", url, str(dest)], check=True)
        # Make shell scripts executable (git may lose +x on some platforms)
        for sh in dest.rglob("*.sh"):
            sh.chmod(sh.stat().st_mode | 0o111)


def _discover_paths() -> Paths:
    """Auto-discover all paths from CWD, with env var overrides.

    Clones kivy and thorvg-cython if they don't exist yet.
    """
    root = Path.cwd()

    def p(env_key: str, default: Path) -> Path:
        val = os.environ.get(env_key)
        return Path(val).resolve() if val else default

    kivy_src  = p("KIVY_SRC",            root / "kivy")
    tc_src    = p("THORVG_CYTHON_SRC",   root / "thorvg-cython")
    kt_src    = p("KIVY_THOR_SRC",       root / "kivy-thor")

    _clone_if_missing(kivy_src, REPOS["kivy"])
    _clone_if_missing(tc_src,   REPOS["thorvg-cython"])

    kivy_deps = p("KIVY_DEPS_ROOT",      kivy_src / "kivy-dependencies")

    return Paths(
        wheelhouse        = p("WHEELHOUSE",          root / "wheelhouse"),
        kivy_src          = kivy_src,
        thorvg_cython_src = tc_src,
        kivy_thor_src     = kt_src,
        kivy_deps         = kivy_deps,
        ios_kivy_deps     = p("IOS_KIVY_DEPS_ROOT",  kivy_src / "ios-kivy-dependencies"),
        angle_lib_dir     = p("ANGLE_LIB_DIR",       kivy_deps / "dist" / "lib"),
        angle_include_dir = p("ANGLE_INCLUDE_DIR",   kivy_deps / "dist" / "include"),
        thorvg_capi_include = p("THORVG_CAPI_INCLUDE", tc_src / "thorvg" / "src" / "bindings" / "capi"),
    )


def main() -> None:
    # Hidden callback used by cibuildwheel's CIBW_REPAIR_WHEEL_COMMAND
    if len(sys.argv) >= 2 and sys.argv[1] == "_repair-thorgpu-wheel":
        ThorGPU.repair_wheel(sys.argv[2])
        return

    parser = argparse.ArgumentParser(
        description="Build wheels for the Kivy-Thor stack.",
    )
    parser.add_argument(
        "builder",
        choices=[*BUILDERS, "all"],
        help="Which package to build (or 'all' for the full chain).",
    )
    parser.add_argument(
        "platform",
        choices=["macos", "ios", "all"],
        help="Target platform (or 'all' for macOS + iOS).",
    )
    args = parser.parse_args()

    paths = _discover_paths()
    paths.wheelhouse.mkdir(parents=True, exist_ok=True)

    names = BUILD_ORDER if args.builder == "all" else [args.builder]
    platforms = (
        [Platform.MACOS, Platform.IOS]
        if args.platform == "all"
        else [Platform(args.platform)]
    )
    builders = [BUILDERS[n](paths) for n in names]

    log(f"Wheelhouse: {paths.wheelhouse}")
    for builder in builders:
        for platform in platforms:
            builder.build(platform)

    log("All requested builds complete.")


if __name__ == "__main__":
    main()
