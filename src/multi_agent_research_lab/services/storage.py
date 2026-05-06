"""Local storage for benchmark artifacts."""

from pathlib import Path


class LocalArtifactStore:
    """Small local store for reports and trace exports."""

    def __init__(self, root: Path = Path("reports")) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write_text(self, relative_path: str, content: str) -> Path:
        """Write text content below the store root and return the written path."""

        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path
