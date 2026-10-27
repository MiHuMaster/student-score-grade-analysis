"""Convert the user-supplied transparent PNG to Windows icon sizes."""
from pathlib import Path
from PIL import Image

root = Path(__file__).resolve().parents[1]
with Image.open(root / "release/desktop-icon-source.png") as source:
    image = source.convert("RGBA")
    image.thumbnail((256, 256), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    canvas.alpha_composite(image, ((256 - image.width) // 2, (256 - image.height) // 2))
    canvas.save(root / "release/app.ico", sizes=[(n, n) for n in (16, 24, 32, 48, 64, 128, 256)])
