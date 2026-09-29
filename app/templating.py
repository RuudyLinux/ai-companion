import os

from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from markupsafe import Markup, escape

from core.security import CSRF_FORM_FIELD

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))


def asset_version(relative_path: str) -> int:
    """File mtime as a cache-busting query param — browsers stop serving stale CSS/JS
    from cache the moment the file actually changes, no manual version bumps needed."""
    try:
        return int(os.path.getmtime(os.path.join(os.path.dirname(__file__), relative_path)))
    except OSError:
        return 0


@pass_context
def csrf_token(context) -> str:
    request = context.get("request")
    return getattr(request.state, "csrf_token", "") if request is not None else ""


@pass_context
def csrf_input(context) -> Markup:
    return Markup(f'<input type="hidden" name="{CSRF_FORM_FIELD}" value="{escape(csrf_token(context))}">')


templates.env.globals["asset_version"] = asset_version
templates.env.globals["csrf_token"] = csrf_token
templates.env.globals["csrf_input"] = csrf_input
