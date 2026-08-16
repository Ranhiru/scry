import pytest

from tools.dsl_indexer.text_utils import _split_identifier, _stem, tokenize, tokenize_path
from tools.dsl_indexer.keyword_index import build_keyword_index, search_keyword_index


class TestStem:
    """Tests verifying Snowball English stemmer behaviour on key terms."""

    def test_plural_s(self):
        assert _stem("tests") == "test"
        assert _stem("methods") == "method"
        assert _stem("elements") == "element"
        assert _stem("tokens") == "token"

    def test_plural_es(self):
        assert _stem("classes") == "class"
        assert _stem("processes") == "process"
        assert _stem("boxes") == "box"

    def test_plural_ies(self):
        assert _stem("queries") == _stem("query")
        assert _stem("utilities") == _stem("utility")
        assert _stem("factories") == _stem("factory")

    def test_ing_forms(self):
        assert _stem("testing") == "test"
        assert _stem("finding") == "find"
        assert _stem("building") == "build"
        assert _stem("calling") == "call"
        assert _stem("running") == "run"
        assert _stem("writing") == "write"

    def test_ed_forms(self):
        assert _stem("tested") == "test"
        assert _stem("called") == "call"
        assert _stem("configured") == _stem("configuration")

    def test_er_forms(self):
        # Snowball keeps -er on some words (helper, builder) but that's fine —
        # both sides of index/query get the same stem
        assert _stem("helper") == _stem("helpers")
        assert _stem("builder") == _stem("builders")
        assert _stem("finder") == _stem("finders")

    def test_ly(self):
        assert _stem("quickly") == "quick"

    def test_consistent_pairs(self):
        """The key property: inflected forms stem to the same value."""
        pairs = [
            ("test", "tests"), ("test", "testing"),
            ("method", "methods"),
            ("element", "elements"),
            ("find", "finding"),
            ("build", "building"),
            ("call", "calling"), ("call", "called"),
            ("run", "running"),
            ("write", "writing"),
            ("class", "classes"),
            ("process", "processes"),
            ("query", "queries"),
            ("utility", "utilities"),
        ]
        for a, b in pairs:
            assert _stem(a) == _stem(b), f"_stem({a!r})={_stem(a)!r} != _stem({b!r})={_stem(b)!r}"

    def test_no_strip_needed(self):
        assert _stem("orbit") == "orbit"
        assert _stem("element") == "element"
        assert _stem("test") == "test"


class TestSplitIdentifier:
    def test_pascal_case(self):
        assert _split_identifier("ElementFinder") == ["elementfinder", "element", "finder"]

    def test_camel_case(self):
        assert _split_identifier("findElement") == ["findelement", "find", "element"]

    def test_long_pascal(self):
        result = _split_identifier("FindElementById")
        assert "findelementbyid" in result
        assert "find" in result
        assert "element" in result
        assert "id" in result

    def test_acronym_then_word(self):
        result = _split_identifier("XMLParser")
        assert "xmlparser" in result
        assert "xml" in result
        assert "parser" in result

    def test_number_boundary(self):
        result = _split_identifier("Vector3D")
        assert "vector3d" in result
        assert "vector" in result

    def test_plain_word(self):
        assert _split_identifier("hello") == ["hello"]

    def test_single_char(self):
        assert _split_identifier("I") == ["i"]

    def test_interface_prefix(self):
        result = _split_identifier("IElement")
        assert "ielement" in result
        assert "element" in result

    def test_all_caps(self):
        assert _split_identifier("HTML") == ["html"]


class TestTokenize:
    def test_basic(self):
        result = tokenize("hello world")
        assert result == ["hello", "world"]

    def test_camel_case_in_text(self):
        result = tokenize("use ElementFinder to find")
        assert _stem("elementfinder") in result
        assert "element" in result
        assert "find" in result

    def test_stemming_applied(self):
        result = tokenize("writing tests for methods")
        assert "write" in result    # writing -> write
        assert "test" in result     # tests -> test
        assert "method" in result   # methods -> method

    def test_plurals_stemmed(self):
        result = tokenize("elements helpers utilities")
        assert "element" in result
        assert _stem("helpers") in result
        assert _stem("utilities") in result

    def test_stopword_removal(self):
        result = tokenize("the quick and the slow")
        assert "the" not in result
        assert "and" not in result
        assert "quick" in result
        assert "slow" in result

    def test_single_char_removal(self):
        result = tokenize("a b cd")
        assert "cd" in result
        assert len(result) == 1

    def test_empty_string(self):
        assert tokenize("") == []

    def test_preserves_numbers(self):
        result = tokenize("version2 test")
        assert "version2" in result or "version" in result


class TestTokenizePath:
    def test_basic_path(self):
        result = tokenize_path("src/utils/helper.ts")
        assert "src" in result
        assert _stem("utils") in result
        assert _stem("helper") in result
        assert "ts" not in result

    def test_csharp_path(self):
        result = tokenize_path("Orbit.Search.Core.Test.Utils/ElementFinder.cs")
        assert "search" in result
        assert "orbit" in result
        assert "core" in result
        assert "test" in result
        assert _stem("utils") in result
        assert _stem("elementfinder") in result
        assert "element" in result
        assert _stem("finder") in result
        assert "cs" not in result

    def test_dotnet_namespace_path(self):
        result = tokenize_path("orbit.search.core/src/Orbit.Search.Core.Test.Utils/ElementFinder.cs")
        assert "search" in result
        assert "orbit" in result
        assert "core" in result
        assert "src" in result
        assert "test" in result
        assert _stem("utils") in result
        assert "element" in result
        assert _stem("finder") in result

    def test_empty_path(self):
        assert tokenize_path("") == set()

    def test_extensions_excluded(self):
        result = tokenize_path("readme.md")
        assert "md" not in result
        assert _stem("readme") in result

    def test_hyphenated_segments(self):
        result = tokenize_path("ui-builder/my-component.tsx")
        assert "ui" in result
        assert _stem("builder") in result
        assert _stem("component") in result
        assert "tsx" not in result


class TestIntegration:
    def test_element_finder_surfaced(self):
        """Build a mini index with an ElementFinder-like chunk and verify it's found."""
        chunks = [
            {
                "chunk_id": "c1",
                "repo": "orbit.search.core",
                "path": "Orbit.Search.Core.Test.Utils/ElementFinder.cs",
                "section": "ElementFinder",
                "line_start": 1,
                "line_end": 30,
                "content": (
                    "public static class ElementFinder\n"
                    "{\n"
                    "    public static IElement FindElementById(string id)\n"
                    "    {\n"
                    "        // helper method for locating elements in test scenarios\n"
                    "    }\n"
                    "}"
                ),
            },
            {
                "chunk_id": "c2",
                "repo": "orbit.docs",
                "path": "docs/getting-started.md",
                "section": "Getting Started",
                "line_start": 1,
                "line_end": 20,
                "content": (
                    "# Getting Started with Orbit\n"
                    "This guide covers setting up your development environment.\n"
                    "Install dependencies and run the build."
                ),
            },
        ]

        index = build_keyword_index(chunks)

        # The original failing query — stemming makes "tests"→"test", "methods"→"method"
        results = search_keyword_index(
            index, "helper methods available when writing tests for orbit web sdk",
            top_k=5, repo_filter=[],
        )
        assert results[0]["path"] == "Orbit.Search.Core.Test.Utils/ElementFinder.cs"

        # Targeted query
        results2 = search_keyword_index(index, "ElementFinder test utils", top_k=5, repo_filter=[])
        assert results2[0]["path"] == "Orbit.Search.Core.Test.Utils/ElementFinder.cs"

        # Verb-form query
        results3 = search_keyword_index(index, "find element by id", top_k=5, repo_filter=[])
        assert results3[0]["path"] == "Orbit.Search.Core.Test.Utils/ElementFinder.cs"
