from bbv2.relevance import is_relevant, keyword_tokens
from bbv2.util import strip_html, titlecase


def test_titlecase():
    assert titlecase("crypto") == "Crypto"
    assert titlecase("world cup news") == "World Cup News"
    assert titlecase("BTC markets") == "BTC Markets"  # keeps acronym case


def test_strip_html():
    assert strip_html("<p>Hello <a href='x'>link</a></p>") == "Hello link"
    assert strip_html("a &amp; b") == "a & b"
    assert strip_html(None) == ""


def test_relevance_keeps_on_topic_drops_off_topic():
    kws = keyword_tokens("crypto", "", ["bitcoin", "ethereum", "solana", "btc"])
    # on-topic (spelled-out crypto entities, or mentions "crypto")
    assert is_relevant("Solana surpasses NYSE in spot volume", "", kws)
    assert is_relevant("Belgium vs Iran World Cup sparks crypto prediction market", "", kws)
    # off-topic stories that leaked in from a crypto aggregator source
    assert not is_relevant("Endrick makes World Cup debut for Brazil in 3-0 rout", "", kws)
    assert not is_relevant("Turkey XI announces starting lineup for World Cup", None, kws)


def test_no_keywords_keeps_everything():
    assert is_relevant("anything at all", "", set())
