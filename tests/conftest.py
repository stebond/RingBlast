import pytest

from ringblast import db, plotstyle


@pytest.fixture(autouse=True)
def isolated_user_files(tmp_path, monkeypatch):
    monkeypatch.setenv("RINGBLAST_NO_UPDATE_CHECK", "1")   # no network access from tests
    """Tests never touch the real ~/.ringblast (user databases, plot style)."""
    monkeypatch.setattr(db, "USER_DIR", tmp_path / "user")
    monkeypatch.setattr(plotstyle, "STYLE_FILE", tmp_path / "user" / "plot_style.json")
    plotstyle.set_style(plotstyle.PlotStyle())
    yield
    plotstyle.set_style(plotstyle.PlotStyle())
