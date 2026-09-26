"""Make the web versions of rank-card backgrounds: an animated WebP and a first-frame still, both 480 px wide.

Run by hand, never imported by the cog:

    python unicornia/tools/bg_webp.py path/to/unicornia-astro/public/images/Astolfo.gif ...

Each image gets <name>.webp and <name>-still.webp next to it. The script prints the `preview` and `still` lines to
paste into xp_config.yml. Deploy the files with the Astro site before the config that points at them.
"""

import sys
from pathlib import Path

from PIL import Image, ImageSequence

WIDTH = 480
BASE_URL = "https://unicornia.net/images/"
WEBP = {"quality": 70, "method": 4}


def _resize(frame: Image.Image) -> Image.Image:
    frame = frame.convert("RGBA")
    if frame.width <= WIDTH:
        return frame
    return frame.resize((WIDTH, round(frame.height * WIDTH / frame.width)), Image.Resampling.LANCZOS)


def convert(source: Path) -> tuple[Path, Path]:
    animated, still = source.with_suffix(".webp"), source.with_name(f"{source.stem}-still.webp")
    with Image.open(source) as image:
        frames, durations = [], []
        for frame in ImageSequence.Iterator(image):
            frames.append(_resize(frame))
            durations.append(frame.info.get("duration", image.info.get("duration", 100)) or 100)
        frames[0].save(still, "WEBP", **WEBP)
        frames[0].save(animated, "WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0, **WEBP)
    return animated, still


def main(paths: list[str]) -> None:
    for path in map(Path, paths):
        animated, still = convert(path)
        print(f"# {path.name}\n      preview: {BASE_URL}{animated.name}\n      still: {BASE_URL}{still.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
