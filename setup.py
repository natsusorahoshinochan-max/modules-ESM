"""Package module-owned browser resources alongside Python registrations."""

from pathlib import Path
import subprocess

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildModuleUi(build_py):
    def run(self) -> None:
        super().run()
        root = Path(__file__).resolve().parent
        subprocess.run(
            ["node", str(root / "webui/tools/build-module-ui.mjs"), str(Path(self.build_lib).resolve())],
            cwd=root,
            check=True,
        )


setup(cmdclass={"build_py": BuildModuleUi})
