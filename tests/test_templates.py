"""Template manager tests."""

from pixoo.common.models import default_project
from pixoo.studio.template_manager import TemplateManager


def test_list_and_apply_templates():
    tm = TemplateManager()
    names = {t["id"] for t in tm.list_templates()}
    assert "weather_paris" in names
    assert "bitcoin_price" in names
    assert "system_monitor" in names
    project = default_project()
    tm.apply_to_project(project, "weather_paris")
    assert any(s.id == "weather" for s in project.sources)
    assert any(s.id.startswith("scr_weather") for s in project.screens)
