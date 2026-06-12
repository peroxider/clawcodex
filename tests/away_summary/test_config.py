from clawcodex_ext.away_summary.config import AwaySummaryConfig


def test_default_config_values() -> None:
    cfg = AwaySummaryConfig.from_mapping({})
    assert cfg.enabled is True
    assert cfg.idle_seconds == 300
    assert cfg.recap_command_enabled is True
    assert cfg.min_turns == 1


def test_config_accepts_idle_minutes_fallback() -> None:
    cfg = AwaySummaryConfig.from_mapping({"idle_minutes": 3})
    assert cfg.idle_seconds == 180


def test_config_normalizes_invalid_values() -> None:
    cfg = AwaySummaryConfig.from_mapping(
        {
            "enabled": "false",
            "idle_seconds": -5,
            "recap_command_enabled": "off",
            "min_turns": -1,
            "max_input_tokens": 10,
            "max_output_tokens": 10,
        }
    )
    assert cfg.enabled is False
    assert cfg.idle_seconds == 1
    assert cfg.recap_command_enabled is False
    assert cfg.min_turns == 0
    assert cfg.max_input_tokens == 256
    assert cfg.max_output_tokens == 64
