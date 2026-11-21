"""Render the report's SVG diagrams to PNG with headless Chrome.

Usage: python render.py [name ...]   (no names = every figure)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "figures"
SVGDIR = HERE.parent / "figures" / "svg"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
SCALE = 3  # px per svg unit; 760 px wide -> 2280 px, about 400 dpi at 5.75 in

sys.path.insert(0, str(HERE))
import figures_a as A  # noqa: E402

FIGS = {
    "fig3_1_architecture": A.system_architecture,
    "fig3_2_component": A.component_diagram,
    "fig3_2_1_deployment": A.deployment_diagram,
    "fig3_3_activity": A.activity_diagram,
    "fig3_5_dfd": A.dfd_level1,
    "fig3_8_class": A.class_diagram,
}
try:
    import figures_b as B  # noqa: E402
    FIGS.update(B.FIGS)
except ImportError:
    pass


def render(name: str) -> Path:
    s = FIGS[name]()
    SVGDIR.mkdir(parents=True, exist_ok=True)
    svg_path = SVGDIR / f"{name}.svg"
    svg_path.write_text(s.svg(), encoding="utf-8")
    html = SVGDIR / f"{name}.html"
    html.write_text(f"<!doctype html><html><body style='margin:0;background:#fff'>{s.svg()}</body></html>",
                    encoding="utf-8")
    png = OUT / f"{name}.png"
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    f"--window-size={s.w},{s.h}", f"--force-device-scale-factor={SCALE}",
                    f"--screenshot={png}", html.as_uri()],
                   check=True, capture_output=True)
    return png


if __name__ == "__main__":
    names = sys.argv[1:] or list(FIGS)
    for n in names:
        print(render(n))
