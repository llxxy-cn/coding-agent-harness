import subprocess
import sys
from pathlib import Path


__test__ = False


def test_timeout_tree() -> None:
    subprocess.Popen([sys.executable, str(Path(__file__).with_name("spawn_child.py"))])
    while True:
        pass
