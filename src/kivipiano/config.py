from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path

    @classmethod
    def default(cls) -> "AppPaths":
        return cls(Path.home() / ".kivipiano")

    @property
    def library_dir(self) -> Path:
        return self.data_dir / "library"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"
