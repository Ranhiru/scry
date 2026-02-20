import re
from typing import List, Set

import snowballstemmer

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
    "you",
    "your",
}

# Regex to detect camelCase/PascalCase boundaries:
#   aB  — lowercase followed by uppercase
#   ABc — run of uppercase followed by uppercase+lowercase (e.g. XML|Parser)
#   a1  — letter followed by digit
#   1a  — digit followed by letter
_CAMEL_BOUNDARY = re.compile(
    r"(?<=[a-z])(?=[A-Z])"        # aB
    r"|(?<=[A-Z])(?=[A-Z][a-z])"  # ABc
    r"|(?<=[a-zA-Z])(?=[0-9])"    # a1 / A1
    r"|(?<=[0-9])(?=[a-zA-Z])"    # 1a / 1A
)

_PATH_EXTENSIONS = {"cs", "ts", "tsx", "js", "jsx", "md", "mdx", "json", "xml", "yaml", "yml", "csproj", "sln", "config", "props"}

_stemmer = snowballstemmer.stemmer("english")


def _stem(word: str) -> str:
    """Stem a word using the Snowball English stemmer."""
    return _stemmer.stemWord(word)


def _split_identifier(token: str) -> List[str]:
    """Split a PascalCase/camelCase token into sub-parts plus the original."""
    parts = _CAMEL_BOUNDARY.split(token)
    lowered = token.lower()
    if len(parts) <= 1:
        return [lowered]
    result = [lowered]
    for p in parts:
        pl = p.lower()
        if len(pl) > 1 and pl not in STOPWORDS:
            result.append(pl)
    return result


def tokenize(text: str) -> List[str]:
    raw_tokens = re.findall(r"[a-zA-Z0-9_]+", text)
    expanded = []
    for t in raw_tokens:
        for part in _split_identifier(t):
            stemmed = _stem(part)
            if stemmed not in expanded[-1:]:  # avoid consecutive duplicates
                expanded.append(stemmed)
    return [t for t in expanded if len(t) > 1 and t not in STOPWORDS]


def tokenize_path(path: str) -> Set[str]:
    """Tokenize a file path into searchable terms.

    Splits on /, ., -, _ and applies camelCase splitting to each segment.
    Drops known file extensions.
    """
    segments = re.split(r"[/.\-_]+", path)
    tokens: Set[str] = set()
    for seg in segments:
        if not seg:
            continue
        low = seg.lower()
        if low in _PATH_EXTENSIONS:
            continue
        for t in _split_identifier(seg):
            stemmed = _stem(t)
            if len(stemmed) > 1 and stemmed not in STOPWORDS:
                tokens.add(stemmed)
    return tokens

