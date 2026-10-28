"""CLI: python main.py input.yaml output.png"""

import argparse
import sys

from generator.models import InputError
from generator.render import render_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Generátor Facebook grafik litovle.cz (1080 × 1080 PNG)")
    parser.add_argument("input", help="Vstupní YAML nebo JSON")
    parser.add_argument("output", help="Výstupní PNG")
    parser.add_argument("--resolutions-dir", help="Adresář s exportovanými ročními JSON usneseními")
    args = parser.parse_args()
    try:
        render_file(args.input, args.output, args.resolutions_dir)
    except (InputError, OSError, ValueError) as exc:
        parser.exit(2, f"Chyba: {exc}\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
