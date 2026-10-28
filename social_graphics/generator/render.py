from pathlib import Path

from .layouts import council_summary, waste_change
from .models import CouncilSummary, load_input


def render_file(input_path: str | Path, output_path: str | Path,
                resolutions_dir: str | Path | None = None) -> None:
    model = load_input(Path(input_path), Path(resolutions_dir) if resolutions_dir is not None else None)
    image = council_summary(model) if isinstance(model, CouncilSummary) else waste_change(model)
    output = Path(output_path)
    if output.suffix.lower() != ".png":
        raise ValueError("Výstup musí mít příponu .png.")
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, format="PNG", optimize=True)
