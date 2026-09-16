from ctxguard.core.guards.output_shaper import OutputShaper, STEERING_SENTINEL, STEERING_SUFFIX

def test_output_shaper_levels_and_idempotency():
    # 1. Level 0 returns None
    assert OutputShaper.get_steering_block(0) is None

    # 2. Append to clean prompt
    original = "You are a coding assistant."
    shaped, changed = OutputShaper.shape_system_prompt(original, level=2)
    assert changed is True
    assert STEERING_SENTINEL in shaped
    assert "Concise & Direct" in shaped

    # 3. Idempotent replacement
    reshaped, changed_again = OutputShaper.shape_system_prompt(shaped, level=2)
    assert changed_again is False
    assert reshaped == shaped

    # 4. Level switch replacement
    level3_shaped, level_changed = OutputShaper.shape_system_prompt(shaped, level=3)
    assert level_changed is True
    assert "High-Density" in level3_shaped
    assert shaped.count(STEERING_SENTINEL) == 1
