from importlib import import_module


def test_first_wave_modules_expose_frozen_parent_interfaces() -> None:
    assert hasattr(import_module("manim_workbench_api.auth.service"), "AuthService")
    assert hasattr(import_module("manim_workbench_api.auth.models"), "SessionPrincipal")
    assert hasattr(import_module("manim_workbench_api.projects.service"), "ProjectService")
    assert hasattr(import_module("manim_workbench_api.delivery.service"), "DeliveryService")
