"""
Chụp "ảnh" wiring sự kiện của app Gradio để so sánh trước/sau refactor.

  python tools/wiring_snapshot.py > before.json
  ... refactor ...
  python tools/wiring_snapshot.py > after.json && diff before.json after.json

Mỗi sự kiện: (targets, inputs, outputs, api_name, trigger). Id component được cấp theo thứ tự dựng
giao diện nên ổn định nếu bố cục không đổi. Danh sách được sắp xếp để diff không phụ thuộc thứ tự.
"""
import json
import sys
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
warnings.filterwarnings("ignore")


def snapshot() -> dict:
    from ui.main_ui import create_app

    cfg = create_app().get_config_file()
    deps = []
    for d in cfg["dependencies"]:
        deps.append({
            "targets": sorted(map(str, d.get("targets", []))),
            "inputs": d.get("inputs", []),
            "outputs": d.get("outputs", []),
            "api_name": d.get("api_name"),
            "queue": d.get("queue"),
            "show_progress": d.get("show_progress"),
        })
    deps.sort(key=lambda x: json.dumps(x, sort_keys=True, default=str))
    comps = sorted(
        ((c["id"], c["type"], (c.get("props") or {}).get("label")) for c in cfg["components"]),
        key=lambda x: x[0],
    )
    return {"components": comps, "dependencies": deps}


if __name__ == "__main__":
    json.dump(snapshot(), sys.stdout, ensure_ascii=False, indent=1, sort_keys=True, default=str)
