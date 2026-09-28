import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tiktok = _load("get_tiktok_token")


def test_authorize_url_contains_required_params():
    url = tiktok.build_authorize_url("key123", "https://me.blogspot.com/", "st")
    params = parse_qs(urlparse(url).query)
    assert params["client_key"] == ["key123"]
    assert params["redirect_uri"] == ["https://me.blogspot.com/"]
    assert params["response_type"] == ["code"]
    assert "video.publish" in params["scope"][0]


def test_extract_code_decodes_and_checks_state():
    url = "https://me.blogspot.com/?code=abc%2A123%21&scopes=video.publish&state=st"
    assert tiktok.extract_code(url, "st") == "abc*123!"


@pytest.mark.parametrize("url,message", [
    ("https://me.blogspot.com/?code=x&state=other", "state"),
    ("https://me.blogspot.com/?state=st", "code"),
    ("https://me.blogspot.com/?error=access_denied&error_description=denied&state=st", "거부"),
])
def test_extract_code_errors(url, message):
    with pytest.raises(ValueError, match=message):
        tiktok.extract_code(url, "st")
