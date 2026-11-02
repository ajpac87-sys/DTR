"""
Build the clickable preview: one HTML file with the real screens, every
language, and a pretend server with sample data (preview/mock_api.js).

    python tools/build_preview.py      -> preview/dtr-preview.html
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "dtr" / "static"
OUT = ROOT / "preview" / "dtr-preview.html"


def main() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    body = re.search(r"<body>(.*?)<script", html, re.S).group(1)
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    app = (STATIC / "app.js").read_text(encoding="utf-8")
    mock = (ROOT / "preview" / "mock_api.js").read_text(encoding="utf-8")
    locales = {p.stem: json.loads(p.read_text(encoding="utf-8"))
               for p in sorted((STATIC / "locales").glob("*.json"))}
    # Keep "</script>" inside the data from closing the tag early.
    data = json.dumps(locales, ensure_ascii=False).replace("</", "<\\/")
    page = f"""<title>DTR Preview</title>
<style>
{css}
</style>
<div class="preview-bar">PREVIEW · sample data · nothing is saved · reload to start over</div>
{body.strip()}
<script>window.DTR_LOCALES = {data};
try {{ localStorage.removeItem("dtr_token"); }} catch (e) {{}}</script>
<script>
{mock}
</script>
<script>
{app}
</script>
"""
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({len(page) // 1024} KB)")


if __name__ == "__main__":
    main()
