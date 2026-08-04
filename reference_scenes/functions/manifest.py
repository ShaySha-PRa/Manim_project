"""The fixed Phase 4 function-visualization reference-scene manifest."""

SCENE_MANIFEST: tuple[dict[str, str], ...] = (
    {
        "scene_id": "quadratic_key_features",
        "scene_class": "QuadraticKeyFeaturesScene",
        "source_path": "reference_scenes/functions/quadratic_key_features.py",
        "category": "function_visualization",
    },
    {
        "scene_id": "parabola_parameter_changes",
        "scene_class": "ParabolaParameterChangesScene",
        "source_path": "reference_scenes/functions/parabola_parameter_changes.py",
        "category": "function_visualization",
    },
    {
        "scene_id": "cubic_moving_tangent",
        "scene_class": "CubicMovingTangentScene",
        "source_path": "reference_scenes/functions/cubic_moving_tangent.py",
        "category": "function_visualization",
    },
    {
        "scene_id": "riemann_sum_area",
        "scene_class": "RiemannSumAreaScene",
        "source_path": "reference_scenes/functions/riemann_sum_area.py",
        "category": "function_visualization",
    },
    {
        "scene_id": "sine_parameter_transformations",
        "scene_class": "SineParameterTransformationsScene",
        "source_path": "reference_scenes/functions/sine_parameter_transformations.py",
        "category": "function_visualization",
    },
    {
        "scene_id": "exponential_linear_comparison",
        "scene_class": "ExponentialLinearComparisonScene",
        "source_path": "reference_scenes/functions/exponential_linear_comparison.py",
        "category": "function_visualization",
    },
)
