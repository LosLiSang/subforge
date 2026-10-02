"""纯逻辑单测：DLsite RJ 号归一化与 HTML 解析器。"""

from subforge.dlsite import normalize_rj_code, parse_dlsite_html

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta property="og:title" content="【パンツ超特化】【3時間30分超】パンツの女神たち | DLsite 同人 - R18">
  <meta property="og:image" content="https://img.dlsite.jp/modpub/images2/work/doujin/RJ01307000/RJ01306764_img_main.jpg">
</head>
<body>
  <h1 id="work_name">【パンツ超特化】【3时间30分超】パンツの女神たち</h1>
  <span class="maker_name"><a href="/circle/123.html">VOICE LOVER</a></span>
  <table id="work_outline">
    <tr><th>サークル名</th><td><a href="/circle/123.html">VOICE LOVER</a></td></tr>
    <tr><th>声優</th><td><a href="/author/1.html">陽向葵ゅか</a></td></tr>
    <tr><th>販売日</th><td>2024年12月27日</td></tr>
    <tr><th>ジャンル</th><td>
      <a href="/genre/101.html">ASMR</a>
      <a href="/genre/102.html">耳かき</a>
      <a href="/genre/103.html">甘サド</a>
    </td></tr>
  </table>
</body>
</html>
"""


def test_normalize_rj_code():
    assert normalize_rj_code("rj01306764") == "RJ01306764"
    assert normalize_rj_code("01306764") == "RJ01306764"
    assert normalize_rj_code("RJ123456") == "RJ123456"
    assert normalize_rj_code("vj123456") == "VJ123456"
    assert normalize_rj_code("invalid") == "INVALID"


def test_parse_dlsite_html():
    meta = parse_dlsite_html(SAMPLE_HTML, "RJ01306764")
    assert meta.rj_code == "RJ01306764"
    assert "パンツの女神たち" in meta.title
    assert meta.circle == "VOICE LOVER"
    assert meta.voice_actors == ["陽向葵ゅか"]
    assert "ASMR" in meta.tags
    assert "耳かき" in meta.tags
    assert "甘サド" in meta.tags
    assert meta.release_date == "2024-12-27"
    assert "RJ01306764_img_main.jpg" in meta.cover_url
