"""Gera os formatos de ícone a partir da arte-mestra aprovada."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
MASTER = ASSETS / "branding" / "hollytranscricao-icon-master.png"
RESAMPLING = Image.Resampling.LANCZOS


def _render(source: Image.Image, size: int, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.resize((size, size), RESAMPLING).save(destination, optimize=True)


def _build_macos_icon(source: Image.Image) -> None:
    iconutil = shutil.which("iconutil")
    if iconutil is None:
        return

    definitions = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    with tempfile.TemporaryDirectory(prefix="hollytranscricao_icon_") as temp_dir:
        iconset = Path(temp_dir) / "HollyTranscricao.iconset"
        iconset.mkdir()
        for filename, size in definitions.items():
            _render(source, size, iconset / filename)
        subprocess.run(  # noqa: S603 - executável resolvido por shutil.which
            [iconutil, "-c", "icns", str(iconset), "-o", str(ASSETS / "icon.icns")],
            check=True,
            shell=False,
        )


def main() -> None:
    source = Image.open(MASTER).convert("RGBA")
    _render(source, 1024, ASSETS / "icon_1024.png")
    source.save(
        ASSETS / "icon.ico",
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    for size in (16, 32, 48, 64, 128, 256, 512, 1024):
        _render(
            source,
            size,
            ASSETS / "icons" / "hicolor" / f"{size}x{size}" / "apps" / "hollytranscricao.png",
        )
    _build_macos_icon(source)


if __name__ == "__main__":
    main()
