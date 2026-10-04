"""Storage XHTML to markdown: what is kept, what becomes a placeholder, and the three
promises — no raw HTML, no unsafe link, no image that was not handed in."""

import re

import pytest

from dplanner.modules.spec_confluence.convert import MAX_DEPTH, attachment_names, convert

IMAGES = {"flow.png": "assets/0123456789abcdef.png"}
PAGES = {"Token lifecycle": "https://acme.atlassian.net/wiki/pages/viewpage.action?pageId=2"}


def md(storage, images=IMAGES, pages=PAGES):
    return convert(storage, images, pages)


def test_headings_paragraphs_and_inline_marks():
    out = md(
        "<h2>Auth</h2><p>Hello <strong>world</strong>, <em>you</em> <s>not</s> <code>x`y</code>.</p>"
    )
    assert out == "## Auth\n\nHello **world**, *you* ~~not~~ ``x`y``.\n"


def test_lists_nest_and_tasks_become_checkboxes():
    out = md(
        "<ul><li>one<ul><li>deep</li></ul></li><li>two</li></ul>"
        "<ol><li>first</li><li>second</li></ol>"
        "<ac:task-list><ac:task><ac:task-status>complete</ac:task-status>"
        "<ac:task-body>done</ac:task-body></ac:task><ac:task>"
        "<ac:task-status>incomplete</ac:task-status><ac:task-body>todo</ac:task-body></ac:task>"
        "</ac:task-list>"
    )
    assert out == "- one\n  - deep\n- two\n\n1. first\n2. second\n\n- [x] done\n- [ ] todo\n"


def test_a_table_is_gfm_with_a_header_row_synthesised_when_missing():
    headed = md(
        "<table><tr><th>A</th><th>B</th></tr><tr><td>1|x</td><td><p>2</p></td></tr></table>"
    )
    assert headed == "| A | B |\n| --- | --- |\n| 1\\|x | 2 |\n"
    bare = md("<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>")
    assert bare == "|  |  |\n| --- | --- |\n| a | b |\n"


def test_code_macros_keep_their_cdata_body_verbatim_and_fence_past_backticks():
    out = md(
        '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">py</ac:parameter>'
        '<ac:plain-text-body><![CDATA[print("<b>") ``` ]]></ac:plain-text-body></ac:structured-macro>'
    )
    assert out == '````py\nprint("<b>") ``` \n````\n'
    spaced = md(
        '<ac:structured-macro ac:name="noformat"><ac:plain-text-body><![CDATA[x]] ></ac:plain-text-body></ac:structured-macro>'
    )
    assert spaced == "```\nx\n```\n"


def test_panels_expand_and_excerpt_keep_their_content():
    out = md(
        '<ac:structured-macro ac:name="info"><ac:parameter ac:name="title">Heads up</ac:parameter>'
        "<ac:rich-text-body><p>careful</p></ac:rich-text-body></ac:structured-macro>"
        '<ac:structured-macro ac:name="excerpt"><ac:rich-text-body><p>kept</p></ac:rich-text-body></ac:structured-macro>'
    )
    assert out == "> **Info: Heads up**\n>\n> careful\n\nkept\n"


def test_dynamic_macros_become_a_labelled_placeholder_and_a_diagram_its_preview():
    out = md(
        '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">X-1</ac:parameter></ac:structured-macro>'
        '<ac:structured-macro ac:name="toc"/>'
        '<ac:structured-macro ac:name="drawio"><ac:parameter ac:name="diagramName">flow</ac:parameter></ac:structured-macro>'
        '<ac:structured-macro ac:name="custom"><ac:rich-text-body><p>inside</p></ac:rich-text-body></ac:structured-macro>'
    )
    assert out == (
        "> **Confluence macro `jira` — not exported**\n\n"
        "![drawio diagram](assets/0123456789abcdef.png)\n\n"
        "> **Confluence macro `custom` — not exported**\n\n> inside\n"
    )


def test_images_resolve_only_through_the_map_and_external_ones_are_words():
    out = md(
        '<ac:image ac:alt="Flow"><ri:attachment ri:filename="flow.png"/></ac:image>'
        '<ac:image><ri:attachment ri:filename="../../etc/passwd"/></ac:image>'
        '<ac:image><ri:url ri:value="https://ext/i.png"/></ac:image>'
        '<ac:image><ri:url ri:value="javascript:alert(1)"/></ac:image>'
        '<p><img src="https://ext/j.png"/></p>'
    )
    assert "![Flow](assets/0123456789abcdef.png)" in out
    assert "*[image ../../etc/passwd — not exported]*" in out
    assert "*[external image](https://ext/i.png)*" in out
    assert "javascript" not in out
    assert "assets/" not in out.replace("assets/0123456789abcdef.png", "")


def test_attachment_names_lists_what_a_fetch_must_download():
    storage = (
        '<ac:image><ri:attachment ri:filename="a.png"/></ac:image>'
        '<ac:image><ri:attachment ri:filename="a.png"/></ac:image>'
        '<ac:structured-macro ac:name="gliffy"><ac:parameter ac:name="name">d</ac:parameter></ac:structured-macro>'
        '<ac:link><ri:attachment ri:filename="not-an-image.pdf"/></ac:link>'
    )
    assert attachment_names(storage) == ["a.png", "d.png"]


def test_links_are_http_or_mailto_or_text_and_siblings_link_by_absolute_url():
    out = md(
        '<p><a href="https://x.y/z (1)">ok</a> <a href="javascript:alert(1)">bad</a> '
        '<a href="file:///etc/passwd">local</a> <a href="mailto:a@b.c">mail</a> '
        '<ac:link><ri:page ri:content-title="Token lifecycle"/></ac:link> '
        '<ac:link><ri:page ri:content-title="Stranger"/><ac:plain-text-link-body><![CDATA[see]]></ac:plain-text-link-body></ac:link> '
        '<ac:link><ri:user ri:account-id="abc"/></ac:link> '
        '<ac:link><ri:attachment ri:filename="spec.pdf"/></ac:link></p>'
    )
    assert out == (
        "[ok](https://x.y/z%20%281%29) bad local [mail](mailto:a@b.c) "
        "[Token lifecycle](https://acme.atlassian.net/wiki/pages/viewpage.action?pageId=2) "
        "see @user spec.pdf\n"
    )


def test_no_raw_html_survives_and_text_cannot_open_a_construct():
    out = md(
        "<p>&lt;script&gt;x&lt;/script&gt; [not](a link) *stars* `ticks` snake_case _em_</p>"
        "<script>alert(1)</script><style>p{}</style><iframe src='x'></iframe>"
        "<p># not a heading</p><p>- not a list</p><p>&gt; not a quote</p>"
    )
    assert "<" not in out.replace("\\<", "")
    assert out == (
        "\\<script\\>x\\</script\\> \\[not\\](a link) \\*stars\\* \\`ticks\\` snake_case \\_em\\_\n\n"
        "\\# not a heading\n\n\\- not a list\n\n\\> not a quote\n"
    )
    assert "alert" not in out and "p{}" not in out


def test_the_odd_elements_layouts_mentions_time_emoticons_status_placeholder():
    out = md(
        "<ac:layout><ac:layout-section><ac:layout-cell><p>cell</p></ac:layout-cell></ac:layout-section></ac:layout>"
        '<p><time datetime="2026-09-07"/> <ac:emoticon ac:name="smile"/> '
        '<ac:structured-macro ac:name="status"><ac:parameter ac:name="title">In progress</ac:parameter></ac:structured-macro> '
        "<ac:placeholder>type here</ac:placeholder><ac:inline-comment-marker>marked</ac:inline-comment-marker></p>"
        "<ac:adf-extension><ac:adf-node/></ac:adf-extension><hr/><blockquote><p>q</p></blockquote>"
    )
    assert out == (
        "cell\n\n2026-09-07 :smile: **[IN PROGRESS]** marked\n\n"
        "> **Confluence element — not exported**\n\n---\n\n> q\n"
    )


def test_hostile_nesting_and_an_entity_bomb_do_not_take_the_converter_down():
    deep = "<div>" * 10_000 + "x" + "</div>" * 10_000
    assert md(deep) == "x\n"
    tables = "<table><tr><td>" * (MAX_DEPTH + 10) + "y" + "</td></tr></table>" * (MAX_DEPTH + 10)
    assert isinstance(md(tables), str)  # Bounded by the tree's depth cap; nothing recursed away.
    bomb = "<p>" + "&amp;" * 200_000 + "</p>"
    assert md(bomb).count("&") == 200_000


def test_an_empty_or_unparseable_body_is_empty_markdown():
    assert md("") == ""
    assert md("<p></p><ul></ul>") == ""
    assert md("<<<>>> </p>") in ("\\<\\<\\<\\>\\>\\>\n", "\\<\\<\\<\\>\\>\\> \n")


@pytest.mark.parametrize("text", ["a\u2029b", "line\nbreak", "  spaced   out  "])
def test_whitespace_collapses_inside_a_paragraph(text):
    out = md(f"<p>{text}</p>")
    assert not re.search(r"\s\s", out.strip())
