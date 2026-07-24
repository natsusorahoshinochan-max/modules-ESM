"""Tests for TypeRegistry."""

import pytest
from core import TypeRegistry


class TestTypeRegistry:
    def test_register_new_type(self) -> None:
        tr = TypeRegistry()
        tr.register("protein.sequence")
        assert tr.get("protein.sequence") is not None
        assert tr.get("protein.sequence").type_id == "protein.sequence"

    def test_register_duplicate_raises(self) -> None:
        tr = TypeRegistry()
        tr.register("protein.sequence")
        with pytest.raises(ValueError, match="already registered"):
            tr.register("protein.sequence")

    def test_is_compatible_exact_match(self) -> None:
        tr = TypeRegistry()
        tr.register("protein.sequence")
        tr.register("protein.structure")
        assert tr.is_compatible("protein.sequence", "protein.sequence")
        assert tr.is_compatible("protein.structure", "protein.structure")

    def test_is_compatible_mismatch(self) -> None:
        tr = TypeRegistry()
        tr.register("protein.sequence")
        tr.register("protein.structure")
        assert not tr.is_compatible("protein.sequence", "protein.structure")
        assert not tr.is_compatible("protein.structure", "protein.sequence")

    def test_is_compatible_unregistered_types(self) -> None:
        tr = TypeRegistry()
        # Unregistered types compare by string equality
        assert tr.is_compatible("unknown.type", "unknown.type")
        assert not tr.is_compatible("unknown.a", "unknown.b")

    def test_get_nonexistent(self) -> None:
        tr = TypeRegistry()
        assert tr.get("nonexistent") is None

    def test_list_all_returns_sorted(self) -> None:
        tr = TypeRegistry()
        tr.register("z.type")
        tr.register("a.type")
        tr.register("m.type")
        assert tr.list_all() == ["a.type", "m.type", "z.type"]

    def test_len(self) -> None:
        tr = TypeRegistry()
        assert len(tr) == 0
        tr.register("a")
        tr.register("b")
        assert len(tr) == 2

    def test_register_with_display_name_and_description(self) -> None:
        tr = TypeRegistry()
        tr.register("protein.sequence", "Protein Sequence", "Amino acid sequence")
        info = tr.get("protein.sequence")
        assert info is not None
        assert info.display_name == "Protein Sequence"
        assert info.description == "Amino acid sequence"
