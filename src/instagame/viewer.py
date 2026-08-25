"""Builds a standalone replay page from a recorded match.

The output is a single HTML file with the replay embedded, so it can be opened
from disk, served as a static file, or published anywhere without a backend.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

TEMPLATE_NAME = "viewer_template.html"
DATA_PLACEHOLDER = "__REPLAY_DATA__"
TITLE_PLACEHOLDER = "__TITLE__"
DEFAULT_TITLE = "Supercritical"


def load_template() -> str:
    """Return the viewer template shipped with the package.

    Returns
    -------
    str
        Template source.
    """
    return resources.files(__package__).joinpath(TEMPLATE_NAME).read_text(encoding="utf-8")


def build_page(replay: dict, title: str = DEFAULT_TITLE) -> str:
    """Render a self-contained replay page.

    Parameters
    ----------
    replay : dict
        Replay produced by :meth:`instagame.replay.Recorder.to_dict`.
    title : str, optional
        Page title, by default ``"Supercritical"``.

    Returns
    -------
    str
        Complete HTML.
    """
    payload = json.dumps(replay, separators=(",", ":"))
    # The payload sits inside a <script> block, so a literal closing tag in any
    # string would end the script early.
    payload = payload.replace("</", "<\\/")
    page = load_template().replace(DATA_PLACEHOLDER, payload)
    return page.replace(TITLE_PLACEHOLDER, escape(title))


def escape(text: str) -> str:
    """Escape text for safe inclusion in HTML body content.

    Parameters
    ----------
    text : str
        Raw text.

    Returns
    -------
    str
        Escaped text.
    """
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def write_page(replay: dict, path: Path, title: str = DEFAULT_TITLE) -> Path:
    """Write a replay page to disk.

    Parameters
    ----------
    replay : dict
        Replay to embed.
    path : Path
        Destination file.
    title : str, optional
        Page title.

    Returns
    -------
    Path
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_page(replay, title), encoding="utf-8")
    return path
