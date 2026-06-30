"""Launch the TradingAgents web UI via `tradingagents-web` command."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    if os.environ.get("STREAMLIT_SERVER_SCRIPT_IS_RUNNING"):
        raise SystemExit(
            "❌ web/launch.py 不能作为 streamlit app 运行！\n"
            "正确启动方式（任选其一）：\n"
            "  • tradingagents-web                         (console_script)\n"
            "  • python -m streamlit run web/app.py\n"
            "  • python web/launch.py"
        )
    app_path = Path(__file__).parent / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(app_path)])


if __name__ == "__main__":
    main()
