"""Tests for the central provider registry and the structures derived from it.

These tests guard the refactor that made the provider registry the single
source of truth: they assert that the transcription/translation managers, the
keychain credential whitelist, and the config model-field map all stay in sync
with ``providers/registry.py``, and that a spec pointing at an unresolvable
module is skipped gracefully (the tolerance a follow-up wave depends on).
"""

import importlib

import pytest

import whisper_hud.transcribe as transcribe_module
import whisper_hud.translate as translate_module
from whisper_hud.providers import registry
from whisper_hud.transcribe import TranscriptionManager
from whisper_hud.translate import TranslationManager

# --- Spec integrity ---------------------------------------------------------


def test_specs_have_valid_kinds_and_categories():
    """Every spec declares a coherent kind/category and resolvable module path."""
    for spec in (*registry.TRANSCRIPTION_SPECS, *registry.TRANSLATION_SPECS):
        assert spec.category in {"local", "cloud"}
        assert spec.module.startswith("whisper_hud.providers.")

    for spec in registry.TRANSCRIPTION_SPECS:
        assert spec.kind == "transcription"
    for spec in registry.TRANSLATION_SPECS:
        assert spec.kind == "translation"


def test_cloud_specs_have_credential_vendor_and_local_specs_do_not():
    """Cloud providers must name an API-key vendor; local providers must not."""
    for spec in (*registry.TRANSCRIPTION_SPECS, *registry.TRANSLATION_SPECS):
        if spec.category == "cloud":
            assert spec.credential_vendor is not None
        else:
            assert spec.credential_vendor is None


def test_all_registered_provider_classes_resolve():
    """Each shipped spec's class actually imports (no typos in module/class)."""
    for spec in (*registry.TRANSCRIPTION_SPECS, *registry.TRANSLATION_SPECS):
        assert registry.resolve_provider_class(spec) is not None, spec.id


def test_specs_by_id_is_keyed_per_kind():
    """specs_by_id returns id -> spec maps scoped to a single kind."""
    transcription = registry.specs_by_id("transcription")
    translation = registry.specs_by_id("translation")

    assert set(transcription) == {spec.id for spec in registry.TRANSCRIPTION_SPECS}
    assert set(translation) == {spec.id for spec in registry.TRANSLATION_SPECS}
    # Ids may legitimately overlap across kinds (e.g. "apple", "gemini", "openai").
    assert {"apple", "gemini", "openai"} <= set(transcription) & set(translation)


# --- Managers are built from the specs --------------------------------------


def test_transcription_manager_classes_match_registry():
    """PROVIDER_CLASSES keys/order mirror the resolvable transcription specs."""
    expected_ids = [
        spec.id for spec in registry.TRANSCRIPTION_SPECS if registry.resolve_provider_class(spec) is not None
    ]
    assert list(TranscriptionManager.PROVIDER_CLASSES.keys()) == expected_ids

    # Each entry points at the same class the registry resolves.
    for spec in registry.TRANSCRIPTION_SPECS:
        resolved = registry.resolve_provider_class(spec)
        if resolved is not None:
            assert TranscriptionManager.PROVIDER_CLASSES[spec.id] is resolved


def test_transcription_manager_categories_match_registry():
    """PROVIDER_CATEGORIES groups exactly match the spec categories."""
    expected = {"cloud": [], "local": []}
    for spec in registry.TRANSCRIPTION_SPECS:
        expected[spec.category].append(spec.id)
    assert TranscriptionManager.PROVIDER_CATEGORIES == expected


def test_translation_manager_classes_match_registry():
    """Translation PROVIDER_CLASSES keys/order mirror the resolvable specs."""
    expected_ids = [spec.id for spec in registry.TRANSLATION_SPECS if registry.resolve_provider_class(spec) is not None]
    assert list(TranslationManager.PROVIDER_CLASSES.keys()) == expected_ids


def test_translation_manager_categories_match_registry():
    """Translation PROVIDER_CATEGORIES groups exactly match the spec categories."""
    expected = {"local": [], "cloud": []}
    for spec in registry.TRANSLATION_SPECS:
        expected[spec.category].append(spec.id)
    assert TranslationManager.PROVIDER_CATEGORIES == expected


def test_translation_model_config_fields_match_registry():
    """MODEL_CONFIG_FIELDS contains exactly the specs that declare a model field."""
    expected = {
        spec.id: spec.config_model_field for spec in registry.TRANSLATION_SPECS if spec.config_model_field is not None
    }
    assert TranslationManager.MODEL_CONFIG_FIELDS == expected
    # Apple translation has no persisted model field (always "system").
    assert "apple" not in TranslationManager.MODEL_CONFIG_FIELDS


def test_config_provider_model_fields_match_registry():
    """Config.get_provider_model is backed by the transcription spec field map."""
    from whisper_hud.config import _TRANSCRIPTION_MODEL_FIELDS

    expected = {
        spec.id: spec.config_model_field for spec in registry.TRANSCRIPTION_SPECS if spec.config_model_field is not None
    }
    assert _TRANSCRIPTION_MODEL_FIELDS == expected


def test_config_fields_reference_real_dataclass_attributes():
    """Every config_model_field names an actual Config dataclass attribute."""
    from whisper_hud.config import Config

    fields = set(Config.__dataclass_fields__)
    for spec in (*registry.TRANSCRIPTION_SPECS, *registry.TRANSLATION_SPECS):
        if spec.config_model_field is not None:
            assert spec.config_model_field in fields, spec.id


# --- Fallback ordering ------------------------------------------------------


def test_transcription_fallback_priorities_are_unique_and_local():
    """Fallback targets are local providers with a strict priority ordering."""
    priorities = [
        (spec.fallback_priority, spec.id) for spec in registry.TRANSCRIPTION_SPECS if spec.fallback_priority is not None
    ]
    ordered = [pid for _, pid in sorted(priorities)]
    assert ordered == ["apple", "whisper_local", "parakeet", "qwen3_asr"]

    # No duplicate priorities, and every fallback target is local.
    assert len({p for p, _ in priorities}) == len(priorities)
    local_ids = set(TranscriptionManager.PROVIDER_CATEGORIES["local"])
    assert {pid for _, pid in priorities} <= local_ids


# --- Credential vendor derivation -------------------------------------------


def test_credential_vendors_preserve_order_and_uniqueness():
    """credential_vendors() yields unique vendors in first-appearance order."""
    assert registry.credential_vendors() == ("openai", "gemini", "anthropic")


def test_keychain_providers_derive_from_registry():
    """keychain.PROVIDERS is exactly the registry credential vendor tuple."""
    from whisper_hud import keychain

    assert keychain.PROVIDERS == registry.credential_vendors()
    # Every keychain vendor has both a display name and a live validator.
    for vendor in keychain.PROVIDERS:
        assert vendor in keychain._PROVIDER_DISPLAY_NAMES
        assert vendor in keychain._API_KEY_VALIDATORS


# --- Graceful skip of unresolvable specs ------------------------------------


def _make_ghost_spec(kind: str) -> registry.ProviderSpec:
    return registry.ProviderSpec(
        id="ghost",
        display_name="Ghost",
        kind=kind,
        category="local",
        module="whisper_hud.providers.does_not_exist_xyz",
        class_name="NoSuchProvider",
        credential_vendor=None,
        config_model_field=None,
        requires_download=False,
        fallback_priority=None,
    )


def test_resolve_provider_class_returns_none_for_missing_module():
    """An unresolvable module resolves to None instead of raising."""
    assert registry.resolve_provider_class(_make_ghost_spec("transcription")) is None


def test_resolve_provider_class_returns_none_for_missing_class():
    """A present module with a missing class resolves to None instead of raising."""
    spec = registry.ProviderSpec(
        id="ghost",
        display_name="Ghost",
        kind="transcription",
        category="local",
        module="whisper_hud.providers.registry",  # real module
        class_name="NoSuchClassName",  # missing attribute
        credential_vendor=None,
        config_model_field=None,
        requires_download=False,
        fallback_priority=None,
    )
    assert registry.resolve_provider_class(spec) is None


def test_transcription_manager_skips_unresolvable_spec(monkeypatch):
    """A ghost transcription spec is silently omitted from PROVIDER_CLASSES."""
    original_ids = {spec.id for spec in registry.TRANSCRIPTION_SPECS}
    patched_specs = registry.TRANSCRIPTION_SPECS + (_make_ghost_spec("transcription"),)
    monkeypatch.setattr(transcribe_module.registry, "TRANSCRIPTION_SPECS", patched_specs)

    rebuilt = transcribe_module._resolve_transcription_classes()
    assert "ghost" not in rebuilt
    assert set(rebuilt) == original_ids


def test_translation_manager_skips_unresolvable_spec(monkeypatch):
    """A ghost translation spec is silently omitted from PROVIDER_CLASSES."""
    original_ids = {spec.id for spec in registry.TRANSLATION_SPECS}
    patched_specs = registry.TRANSLATION_SPECS + (_make_ghost_spec("translation"),)
    monkeypatch.setattr(translate_module.registry, "TRANSLATION_SPECS", patched_specs)

    rebuilt = translate_module._resolve_translation_classes()
    assert "ghost" not in rebuilt
    assert set(rebuilt) == original_ids


def test_provider_spec_is_frozen():
    """ProviderSpec instances are immutable so the registry can be shared safely."""
    from dataclasses import FrozenInstanceError

    spec = registry.TRANSCRIPTION_SPECS[0]
    with pytest.raises(FrozenInstanceError):
        spec.id = "mutated"  # type: ignore[misc]


def test_registry_module_is_a_leaf():
    """The registry source must not import keychain/config/managers (cycle guard).

    keychain and config both depend on the registry, so the registry importing
    them back would create an import cycle. This inspects the parsed import
    statements (not comments/docstrings) so it holds regardless of import order.
    """
    import ast

    spec = importlib.util.find_spec("whisper_hud.providers.registry")
    assert spec is not None and spec.origin is not None
    with open(spec.origin, encoding="utf-8") as f:
        tree = ast.parse(f.read())

    forbidden = {"keychain", "config", "transcribe", "translate"}
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.add(alias.name.split(".")[-1])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[-1])

    assert forbidden.isdisjoint(
        imported_modules
    ), f"registry must not import any of {forbidden}; found {imported_modules & forbidden}"
