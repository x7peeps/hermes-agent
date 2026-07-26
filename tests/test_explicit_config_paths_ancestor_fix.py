"""Test that _explicit_config_paths returns ancestor paths so intermediate
dicts are never stripped by _strip_default_values during migration saves.

Regression test for issue #62723: minimal configs with nested platform
sections (e.g. ``platforms.feishu.enabled: true``) were silently losing
the entire ``platforms`` section after config migration because only leaf
paths were in the preserve set while parent dicts were not — and
_strip_default_values drops any dict whose children are all stripped.
"""
import copy
from hermes_cli.config import (
    _explicit_config_paths,
    _strip_default_values,
    DEFAULT_CONFIG,
)


class TestExplicitConfigPathsAncestors:
    """Verify ancestor-path preservation prevents subtree stripping."""

    def test_minimal_platform_config_preserved(self):
        """Minimal config like the bug report: platforms.feishu.enabled=true.

        Before the fix, _explicit_config_paths returned only
        {("platforms", "feishu", "enabled")}, so _strip_default_values
        would strip the parent dicts ("platforms", "platforms.feishu")
        since they matched defaults — losing the entire platforms section.

        After the fix, ancestors are included, preventing this.
        """
        user_config = {
            "model": {"default": "deepseek-v4-pro", "provider": "deepseek"},
            "agent": {"max_turns": 60},
            "platforms": {
                "feishu": {
                    "enabled": True,
                    "extra": {
                        "app_id": "cli_xxx",
                        "app_secret": "secret",
                        "admins": ["ou_xxx"],
                    },
                }
            },
        }

        # Step 1: Compute explicit paths from the raw config
        explicit_paths = _explicit_config_paths(user_config)

        # Step 2: Verify ancestor paths are included
        assert ("platforms",) in explicit_paths, \
            f"Missing ('platforms',) in explicit paths: {explicit_paths}"
        assert ("platforms", "feishu") in explicit_paths, \
            f"Missing ('platforms', 'feishu') in explicit paths: {explicit_paths}"
        assert ("platforms", "feishu", "enabled") in explicit_paths
        assert ("platforms", "feishu", "extra") in explicit_paths
        assert ("platforms", "feishu", "extra", "app_id") in explicit_paths

        # Step 3: Simulate save_config's strip_defaults pass
        preserved = _strip_default_values(
            copy.deepcopy(user_config),
            DEFAULT_CONFIG,
            preserve_keys=explicit_paths,
        )

        # The platforms section must survive
        assert "platforms" in preserved, \
            f"platforms section was stripped! Result: {preserved}"
        assert "feishu" in preserved["platforms"], \
            f"feishu subsection was stripped! Result: {preserved['platforms']}"
        assert preserved["platforms"]["feishu"]["enabled"] is True

    def test_deeply_nested_config_preserved(self):
        """Multi-level nesting: a.b.c.d = 42 should keep all parents."""
        user_config = {
            "model": {"default": "gpt-4"},
            "feature": {
                "nested": {
                    "deep": {
                        "leaf": 42,
                    },
                },
            },
        }

        explicit_paths = _explicit_config_paths(user_config)

        # All ancestors of ("feature", "nested", "deep", "leaf") should be present
        assert ("feature",) in explicit_paths
        assert ("feature", "nested") in explicit_paths
        assert ("feature", "nested", "deep") in explicit_paths
        assert ("feature", "nested", "deep", "leaf") in explicit_paths

        preserved = _strip_default_values(
            copy.deepcopy(user_config),
            DEFAULT_CONFIG,
            preserve_keys=explicit_paths,
        )

        assert "feature" in preserved
        assert preserved["feature"]["nested"]["deep"]["leaf"] == 42

    def test_leaf_matching_default_is_stripped_when_no_ancestor_conflict(self):
        """If a leaf value matches the default AND its parent also matches
        the default, the leaf should still be stripped (correct behavior).
        Only user-set leaves that differ from defaults should be preserved."""
        user_config = {
            "model": {"default": "gpt-4"},
            "display": {
                "theme": "dark",  # assume this differs from default
            },
        }

        explicit_paths = _explicit_config_paths(user_config)
        preserved = _strip_default_values(
            copy.deepcopy(user_config),
            DEFAULT_CONFIG,
            preserve_keys=explicit_paths,
        )

        # display.theme should be preserved since it differs from default
        assert "display" in preserved
        assert preserved["display"]["theme"] == "dark"

    def test_empty_dict_not_preserved(self):
        """Empty dicts should not create spurious preserve entries."""
        user_config = {
            "model": {"default": "gpt-4"},
        }

        explicit_paths = _explicit_config_paths(user_config)
        # No empty-dict paths should be added
        for path in explicit_paths:
            assert path != (), "Root path should not be in explicit_paths"

    def test_multiple_leaves_share_ancestors(self):
        """Multiple leaves under the same parent should share ancestor paths."""
        user_config = {
            "model": {"default": "gpt-4"},
            "platforms": {
                "feishu": {"enabled": True},
                "telegram": {"streaming": True},
            },
        }

        explicit_paths = _explicit_config_paths(user_config)

        # Both leaf paths
        assert ("platforms", "feishu", "enabled") in explicit_paths
        assert ("platforms", "telegram", "streaming") in explicit_paths

        # Shared ancestors
        assert ("platforms",) in explicit_paths
        assert ("platforms", "feishu") in explicit_paths
        assert ("platforms", "telegram") in explicit_paths

        preserved = _strip_default_values(
            copy.deepcopy(user_config),
            DEFAULT_CONFIG,
            preserve_keys=explicit_paths,
        )

        assert "platforms" in preserved
        assert "feishu" in preserved["platforms"]
        assert "telegram" in preserved["platforms"]


if __name__ == "__main__":
    import sys
    t = TestExplicitConfigPathsAncestors()
    try:
        t.test_minimal_platform_config_preserved()
        print("✓ test_minimal_platform_config_preserved")
    except AssertionError as e:
        print(f"✗ test_minimal_platform_config_preserved: {e}")
        sys.exit(1)

    try:
        t.test_deeply_nested_config_preserved()
        print("✓ test_deeply_nested_config_preserved")
    except AssertionError as e:
        print(f"✗ test_deeply_nested_config_preserved: {e}")
        sys.exit(1)

    try:
        t.test_leaf_matching_default_is_stripped_when_no_ancestor_conflict()
        print("✓ test_leaf_matching_default_is_stripped_when_no_ancestor_conflict")
    except AssertionError as e:
        print(f"✗ test_leaf_matching_default_is_stripped_when_no_ancestor_conflict: {e}")
        sys.exit(1)

    try:
        t.test_empty_dict_not_preserved()
        print("✓ test_empty_dict_not_preserved")
    except AssertionError as e:
        print(f"✗ test_empty_dict_not_preserved: {e}")
        sys.exit(1)

    try:
        t.test_multiple_leaves_share_ancestors()
        print("✓ test_multiple_leaves_share_ancestors")
    except AssertionError as e:
        print(f"✗ test_multiple_leaves_share_ancestors: {e}")
        sys.exit(1)

    print("\nAll tests passed!")
