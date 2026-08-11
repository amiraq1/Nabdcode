"""tests/test_semantic_index_versioning.py — ARCH-1: TF-IDF versioning.

Verifies that ``TfIdfIndex`` correctly tracks its format version,
serializes/deserializes with version checking, and signals when a
rebuild is needed.
"""

from collections import Counter

from core.semantic_index import TfIdfIndex


class TestTfIdfVersioning:
    """Tests for the ARCH-1 versioning & persistence API."""

    def test_version_property(self):
        """``version`` returns the class-level ``_VERSION`` string."""
        idx = TfIdfIndex()
        assert idx.version == TfIdfIndex._VERSION

    def test_needs_rebuild_false_on_fresh_instance(self):
        """A freshly constructed index does not need a rebuild."""
        idx = TfIdfIndex()
        assert idx.needs_rebuild() is False

    def test_needs_rebuild_true_after_stale_deserialize(self):
        """Deserializing an older version marks the index as stale."""
        idx = TfIdfIndex()
        stale = {"version": "0.9", "doc_count": 0, "doc_freq": {}, "vocab": {}}
        result = idx.deserialize(stale)
        assert result is False
        assert idx.needs_rebuild() is True

    def test_deserialize_matching_version(self):
        """Deserializing data with the current version succeeds."""
        idx = TfIdfIndex()
        data = idx.serialize()
        result = idx.deserialize(data)
        assert result is True
        assert idx.needs_rebuild() is False

    def test_deserialize_non_dict(self):
        """Passing a non-dict to ``deserialize`` returns False."""
        idx = TfIdfIndex()
        assert idx.deserialize("not a dict") is False
        assert idx.deserialize(None) is False

    def test_serialize_contains_version(self):
        """Serialized output includes the ``version`` key."""
        idx = TfIdfIndex()
        blob = idx.serialize()
        assert "version" in blob
        assert blob["version"] == TfIdfIndex._VERSION

    def test_serialize_round_trip(self):
        """Index state survives a serialize → deserialize round-trip."""
        idx = TfIdfIndex()
        idx._doc_count = 42
        idx._doc_freq = Counter({"hello": 3, "world": 2})
        idx._vocab = {"hello": 1, "world": 2}

        blob = idx.serialize()
        idx2 = TfIdfIndex()
        assert idx2.deserialize(blob) is True
        assert idx2._doc_count == 42
        assert dict(idx2._doc_freq) == {"hello": 3, "world": 2}
        assert idx2._vocab == {"hello": 1, "world": 2}

    def test_deserialize_missing_version_defaults_stale(self):
        """Data without a ``version`` key is treated as stale."""
        idx = TfIdfIndex()
        data = {"doc_count": 1, "doc_freq": {}, "vocab": {}}
        result = idx.deserialize(data)
        assert result is False
        assert idx.needs_rebuild() is True
