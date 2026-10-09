"""让测试无需安装即可 import src/ 下的包（src/ 布局，见 12.8）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
