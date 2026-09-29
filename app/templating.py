import os

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")


def asset_version(relative_path: str) -> int:
    """File mtime as a cache-busting query param — browsers stop serving stale CSS/JS
    from cache the moment the file actually changes, no manual version bumps needed."""
    try:
        return int(os.path.getmtime(os.path.join(os.path.dirname(__file__), relative_path)))
    except OSError:
        return 0


templates.env.globals["asset_version"] = asset_version
