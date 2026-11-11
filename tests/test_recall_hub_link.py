from post_link_policy import (
    YOUDLE_RECALLS_URL,
    article_link_issues,
    ensure_recall_hub_link,
)


def test_recall_post_gets_link_inside_outer_div():
    source = '<div><h2>New grocery safety alerts</h2><p>Check the official notice.</p></div>'
    final = ensure_recall_hub_link(source, is_recall=True)
    assert final.count(YOUDLE_RECALLS_URL) == 1
    assert final.endswith("</div>")
    assert "View all Youdle food recalls" in final
    assert article_link_issues(final, is_recall=True) == []


def test_appends_only_once():
    source = '<div><p>Official recall announcement.</p></div>'
    first = ensure_recall_hub_link(source, is_recall=True)
    assert ensure_recall_hub_link(first, is_recall=True) == first


def test_leaves_shopper_articles_unchanged():
    source = '<div><p>How to save on groceries.</p></div>'
    assert ensure_recall_hub_link(source, is_recall=False) == source


def test_youdle_recalls_link_is_allowed_only_on_recall_posts():
    html = '<p><a href="https://www.youdle.io/recalls">Food safety recalls</a></p>'
    assert article_link_issues(html, is_recall=True) == []
    assert article_link_issues(html, is_recall=False)

def test_legacy_grocerysos_recall_link_is_normalized_without_duplicating():
    original = '<div><p><a href="https://grocerysos.com/recalls">View all GrocerySOS food recalls</a></p></div>'
    final = ensure_recall_hub_link(original, is_recall=True)
    assert final.count(YOUDLE_RECALLS_URL) == 1
    assert "GrocerySOS" not in final
    assert "grocerysos.com" not in final
    assert article_link_issues(final, is_recall=True) == []


def test_unlaunched_brand_is_rejected_in_all_articles():
    html = '<div><p>Learn more about GrocerySOS.</p></div>'
    assert "Prelaunch article contains GrocerySOS branding" in article_link_issues(html)
    assert article_link_issues('<a href="https://grocerysos.com/recalls">Recalls</a>', is_recall=True)
