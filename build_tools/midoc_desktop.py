from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from phanloaivanban.desktop import run


if __name__ == "__main__":
    raise SystemExit(run(Path("data/documents.sqlite")))
