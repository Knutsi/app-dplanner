"""The markdown renderer: DPlanner's subset as safe, deterministic HTML."""

import random
import re

from dplanner.core.markdown import render

# Every tag the renderer emits; what is left after removing them must carry no angle bracket.
_KNOWN_TAG = re.compile(
    r"</?(?:p|h[1-6]|hr|blockquote|ul|ol|li|pre|code|table|thead|tbody|tr|th|td"
    r"|strong|em|del|br|a|img|span)(?: [^<>]*)?>"
)


def _only_known_tags(html: str) -> bool:
    rest = _KNOWN_TAG.sub("", html)
    return "<" not in rest and ">" not in rest


def test_atx_headings_at_every_level_with_optional_closing_hashes() -> None:
    assert render("# Title") == "<h1>Title</h1>"
    assert render("###### Deep ##") == "<h6>Deep</h6>"
    assert render("## Two *words*") == "<h2>Two <em>words</em></h2>"
    assert render("#hashtag") == "<p>#hashtag</p>"
    assert render("####### seven") == "<p>####### seven</p>"


def test_paragraphs_join_lines_and_break_hard_on_two_spaces_or_a_backslash() -> None:
    assert render("one\ntwo") == "<p>one\ntwo</p>"
    assert render("one  \ntwo\\\nthree") == "<p>one<br>\ntwo<br>\nthree</p>"
    assert render("first\n\n\nsecond") == "<p>first</p>\n<p>second</p>"
    assert render("ends  ") == "<p>ends</p>"


def test_an_indented_line_is_paragraph_text_not_code() -> None:
    assert render("    not code") == "<p>not code</p>"


def test_emphasis_strong_and_strike() -> None:
    assert render("**bold** and __bold__") == (
        "<p><strong>bold</strong> and <strong>bold</strong></p>"
    )
    assert render("*em* and _em_") == "<p><em>em</em> and <em>em</em></p>"
    assert render("~~gone~~") == "<p><del>gone</del></p>"
    assert render("*a **b** c*") == "<p><em>a <strong>b</strong> c</em></p>"


def test_an_underscore_inside_a_word_is_a_letter() -> None:
    assert render("snake_case_name stays") == "<p>snake_case_name stays</p>"
    assert render("2 * 3 * 4") == "<p>2 * 3 * 4</p>"


def test_inline_code_is_escaped_and_protects_its_markup() -> None:
    assert render("`*x*` and *y*") == "<p><code>*x*</code> and <em>y</em></p>"
    assert render("a `<b>` tag") == "<p>a <code>&lt;b&gt;</code> tag</p>"
    assert render("``a ` b``") == "<p><code>a ` b</code></p>"


def test_a_backslash_escapes_punctuation() -> None:
    assert render("\\*not em\\*") == "<p>*not em*</p>"
    assert render("\\[x\\](y)") == "<p>[x](y)</p>"


def test_fenced_code_keeps_its_language_and_escapes_its_body() -> None:
    text = "```python\nif a < b:\n    *pass*\n```\nafter"
    assert render(text) == (
        '<pre><code class="language-python">if a &lt; b:\n    *pass*\n</code></pre>\n<p>after</p>'
    )
    assert render("~~~\n```\n~~~") == "<pre><code>```\n</code></pre>"
    assert render("```\nunclosed") == "<pre><code>unclosed\n</code></pre>"


def test_a_list_nests_one_level_by_indentation() -> None:
    text = "- one\n- two\n  - two a\n  - two b\n- three"
    assert render(text) == (
        "<ul>\n<li>one</li>\n<li>two\n<ul>\n<li>two a</li>\n<li>two b</li>\n</ul></li>\n"
        "<li>three</li>\n</ul>"
    )
    assert render("- top\n  1. sub") == "<ul>\n<li>top\n<ol>\n<li>sub</li>\n</ol></li>\n</ul>"


def test_a_list_item_continues_on_the_next_line_and_survives_a_blank_line() -> None:
    assert render("- one\n  more *here*\n- two") == (
        "<ul>\n<li>one\nmore <em>here</em></li>\n<li>two</li>\n</ul>"
    )
    assert render("- a\n\n- b\n* c") == (
        "<ul>\n<li>a</li>\n<li>b</li>\n</ul>\n<ul>\n<li>c</li>\n</ul>"
    )
    assert render("Steps:\n1. a\n2. b") == "<p>Steps:</p>\n<ol>\n<li>a</li>\n<li>b</li>\n</ol>"


def test_an_ordered_list_starts_where_it_says() -> None:
    assert render("1. a\n2. b") == "<ol>\n<li>a</li>\n<li>b</li>\n</ol>"
    assert render("3) c\n4) d") == '<ol start="3">\n<li>c</li>\n<li>d</li>\n</ol>'
    assert render("1.5 million") == "<p>1.5 million</p>"


def test_a_blockquote_holds_markdown_of_its_own() -> None:
    assert render("> Note:\n> - one\n> - two") == (
        "<blockquote>\n<p>Note:</p>\n<ul>\n<li>one</li>\n<li>two</li>\n</ul>\n</blockquote>"
    )
    assert render("> > deep") == (
        "<blockquote>\n<blockquote>\n<p>deep</p>\n</blockquote>\n</blockquote>"
    )


def test_a_rule_is_three_or_more_of_one_character() -> None:
    assert render("---") == "<hr>"
    assert render("* * *") == "<hr>"
    assert render("___") == "<hr>"
    assert render("--") == "<p>--</p>"


def test_a_table_carries_its_alignment_as_classes() -> None:
    text = "| Step | Days | Who |\n|:-----|-----:|:---:|\n| S1 | 2 | *me* |\n| S2 | 3 |\nafter"
    assert render(text) == (
        "<table>\n<thead>\n"
        '<tr><th>Step</th><th class="right">Days</th><th class="center">Who</th></tr>\n'
        "</thead>\n<tbody>\n"
        '<tr><td>S1</td><td class="right">2</td><td class="center"><em>me</em></td></tr>\n'
        '<tr><td>S2</td><td class="right">3</td><td class="center"></td></tr>\n'
        "</tbody>\n</table>\n<p>after</p>"
    )
    assert "<th>a | b</th>" in render("| a \\| b |\n|---|")
    assert render("a | b\nno delimiter") == "<p>a | b\nno delimiter</p>"


def test_an_image_asks_the_callback_for_its_source() -> None:
    asked: list[str] = []

    def source(src: str) -> str | None:
        asked.append(src)
        return "data:image/png;base64,AAAA"

    assert render("![The graph](assets/abc.png)", image_src=source) == (
        '<p><img alt="The graph" src="data:image/png;base64,AAAA"></p>'
    )
    assert asked == ["assets/abc.png"]


def test_an_image_the_callback_declines_is_omitted_in_words() -> None:
    omitted = '<p><span class="md-image-missing">Graph (image omitted)</span></p>'
    assert render("![Graph](assets/x.png)") == omitted
    assert render("![Graph](assets/x.png)", image_src=lambda _: None) == omitted
    assert render("![](x.png)") == '<p><span class="md-image-missing">(image omitted)</span></p>'
    # The alt is its content's plain text: markup inside it is dropped, never emitted.
    assert render("![the `x` *file*](y.png)") == (
        '<p><span class="md-image-missing">the x file (image omitted)</span></p>'
    )


def test_an_http_link_opens_in_a_new_tab_and_a_bare_url_stays_text() -> None:
    assert render("[Docs](https://example.com/a?b=1&c=2)") == (
        '<p><a href="https://example.com/a?b=1&amp;c=2" rel="noopener" target="_blank">Docs</a></p>'
    )
    assert render("see http://example.com now") == "<p>see http://example.com now</p>"


def test_a_link_text_carries_markup_and_a_destination_balanced_parentheses() -> None:
    assert render("[**b** `c`](https://x.y/Foo_(bar))") == (
        '<p><a href="https://x.y/Foo_(bar)" rel="noopener" target="_blank">'
        "<strong>b</strong> <code>c</code></a></p>"
    )
    assert render("[![a](i.png)](https://x.y)") == (
        '<p><a href="https://x.y" rel="noopener" target="_blank">'
        '<span class="md-image-missing">a (image omitted)</span></a></p>'
    )
    # A destination is what was typed, minus backslash escapes.
    assert render("[x](https://a.b/some\\_page) <https://a.b/\\*>") == (
        '<p><a href="https://a.b/some_page" rel="noopener" target="_blank">x</a> '
        '<a href="https://a.b/*" rel="noopener" target="_blank">https://a.b/*</a></p>'
    )


def test_a_mailto_link_is_a_link() -> None:
    assert render("[Mail](mailto:a@b.c)") == (
        '<p><a href="mailto:a@b.c" rel="noopener" target="_blank">Mail</a></p>'
    )


def test_a_relative_link_renders_as_its_text_alone() -> None:
    assert render("[the spec](assets/spec.pdf)") == (
        '<p><span class="md-link-inert">the spec</span></p>'
    )


def test_a_javascript_or_file_url_is_never_a_link() -> None:
    html = render("[click](javascript:alert(1)) [f](file:///etc/passwd)")
    assert html == (
        '<p><span class="md-link-inert">click</span> <span class="md-link-inert">f</span></p>'
    )
    assert "href" not in html


def test_an_autolink_in_angle_brackets_is_a_link_when_its_scheme_is() -> None:
    assert render("<https://example.com/x>") == (
        '<p><a href="https://example.com/x" rel="noopener" target="_blank">'
        "https://example.com/x</a></p>"
    )
    assert render("<javascript:alert(1)>") == (
        '<p><span class="md-link-inert">javascript:alert(1)</span></p>'
    )
    assert render("<div>") == "<p>&lt;div&gt;</p>"


def test_html_in_the_source_is_text_everywhere() -> None:
    assert render("<script>alert(1)</script>") == "<p>&lt;script&gt;alert(1)&lt;/script&gt;</p>"
    assert render("AT&T &copy;") == "<p>AT&amp;T &amp;copy;</p>"
    assert render("# <b>x</b>") == "<h1>&lt;b&gt;x&lt;/b&gt;</h1>"
    assert render('[say "hi"](https://x.y/?q="a")') == (
        '<p><a href="https://x.y/?q=&quot;a&quot;" rel="noopener" target="_blank">'
        "say &quot;hi&quot;</a></p>"
    )
    assert render('![<x>"](y.png)') == (
        '<p><span class="md-image-missing">&lt;x&gt;&quot; (image omitted)</span></p>'
    )


def test_nothing_renders_as_nothing() -> None:
    assert render("") == ""
    assert render("  \n\t\n") == ""


def test_garbage_renders_without_raising() -> None:
    controls = "".join(chr(i) for i in range(32))
    for text in (
        controls,
        "\x00zero",
        "```\n~~~\n",
        "**",
        "*",
        "_",
        "[",
        "![",
        "[x](",
        "|",
        "|---|",
        "- \n1. \n> ",
        "  " * 400 + "- deep",
    ):
        html = render(text)
        assert isinstance(html, str)
        assert _only_known_tags(html), text
    wall = render(">" * 40 + " x")
    assert wall.count("<blockquote>") == wall.count("</blockquote>")
    assert "&gt;" in wall


def test_random_markdown_soup_renders_safely_and_the_same_twice() -> None:
    rng = random.Random(7)
    alphabet = 'ab \n*_~`#>-+1.)[]()!|:<>\\"&\t'
    for _ in range(300):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randrange(80)))
        html = render(text)
        assert html == render(text)
        assert "\x00" not in html
        assert _only_known_tags(html), text


DOCUMENT = """# Handoff

The parser is **done**; see `core/markdown.py` and [the spec](https://example.com).

- Blocks first
  - then inline
- Tables:

| what | days |
|------|-----:|
| this | 2 |

> Nothing stored, ~~everything~~ *most things* derived.

```py
render("x")
```
"""


def test_the_same_text_renders_the_same_html() -> None:
    first = render(DOCUMENT)
    assert first == render(DOCUMENT)
    for opened in (
        "<h1>",
        "<p>",
        "<ul>",
        "<table>",
        "<blockquote>",
        '<pre><code class="language-py">',
    ):
        assert opened in first
    assert _only_known_tags(first)
