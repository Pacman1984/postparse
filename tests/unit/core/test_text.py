"""Tests for hashtag and mention extraction (``postparse.core.text``)."""

from __future__ import annotations

import pytest

from postparse.core.text import extract_hashtags, extract_mentions


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, []),
        ("", []),
        ("Pasta #Rezept #Pasta #rezept!", ["rezept", "pasta"]),
        ("#über #Café #日本語 #snake_case", ["über", "café", "日本語", "snake_case"]),
        ("Cafe" + chr(0x301) + " #Cafe" + chr(0x301), ["caf" + chr(0xE9)]),  # NFC
        ("Platz #1 und #2024 aber #top10", ["top10"]),
        ("https://example.org/page#section and www.x.org/#a", []),
        ("price&#39;s a#b x/#c", []),
        ("(#klammer) #ende.", ["klammer", "ende"]),
        ("##double #a#b", ["a"]),  # glued sigils are not tags
    ],
)
def test_extract_hashtags(text: str | None, expected: list[str]) -> None:
    assert extract_hashtags(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (None, []),
        ("Danke @Koch.Profi und @koch.profi!", ["koch.profi"]),
        ("mail me@example.org or a.b+c@mail.example.com", []),
        ("@chef. @x_y, @Ünal", ["chef", "x_y", "ünal"]),
        ("see https://medium.com/@author/post", []),
        ("@@double", []),
        ("(@paren) end", ["paren"]),
    ],
)
def test_extract_mentions(text: str | None, expected: list[str]) -> None:
    assert extract_mentions(text) == expected
