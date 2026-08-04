"""Tests rendu / cache."""

from pixoo_studio.domain.models import default_project
from pixoo_studio.render.engine import RenderEngine


def test_render_and_cache():
    eng = RenderEngine()
    eng.fonts.preload()
    project = default_project()
    scr = project.screens[0]
    values = {"src_cpu": 42.0, "src_disk": 60.0}
    a = eng.render_screen(scr, project, values, anim_t=0.0)
    b = eng.render_screen(scr, project, values, anim_t=0.0)
    assert a.size == (64, 64)
    assert b.size == (64, 64)
    # cache hit path
    assert eng.cache.get(eng.cache_key(scr, values, anim_t=0.0)) is not None


def test_transition_fade():
    eng = RenderEngine()
    project = default_project()
    a = eng.render_screen(project.screens[0], project, {"src_cpu": 10}, anim_t=0)
    b = eng.render_screen(project.screens[1], project, {"src_disk": 50}, anim_t=0)
    mid = eng.transition(a, b, 0.5, "fade")
    assert mid.size == (64, 64)
