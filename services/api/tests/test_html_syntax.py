import pytest
from app.html_syntax import validate_html_styles


@pytest.mark.parametrize('html', [
    '<style>.topbar{padding:0 max(24px,calc((100% - 1120px)/2);display:flex}.hero{display:grid}</style>',
    '<style>.hero{display:grid</style>',
    '<div style="width:calc(100% - 20px">正文</div>',
])
def test_broken_css_cannot_silently_hide_following_layout(html):
    with pytest.raises(ValueError, match='CSS 括号'):
        validate_html_styles(html)


@pytest.mark.parametrize('html', [
    '<style>.topbar{padding:0 max(24px,calc((100% - 1120px)/2));display:flex}.hero{display:grid}</style>',
    '<style>/* ([ */ .x:after{content:"(见说明) ["} @media(width < 600px){.x{width:calc(100% - 1px)}}</style>',
    '<style>.x\\[1\\]{background:url("a(b).png");--items:{name:value}}</style>',
    '<div style="font-family:&quot;Hello (&quot;;width:100%">内容</div><script>let text="{";</script>',
    '<p>普通文字：(未完成</p>',
])
def test_valid_css_strings_comments_nested_rules_and_html_text_are_preserved(html):
    validate_html_styles(html)
