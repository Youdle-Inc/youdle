"""Newsletter regression checks without external services or paid model calls."""
from mailchimp_campaign import MailchimpCampaign


def test_newsletter_preserves_distinct_saved_images_and_published_article_urls():
    mailer = object.__new__(MailchimpCampaign)
    html = mailer.create_newsletter_html(
        [
            {
                "title": "Beef prices are rising. Here's the cut holding steady",
                "url": "https://news.youdle.io/2026/10/beef-prices.html",
                "summary": "Practical details about the grocery prices shoppers face.",
                "image_url": "https://i.ibb.co/test1/beef.jpg",
            },
            {
                "title": "Your grocery cart could cost less with one comparison",
                "url": "https://news.youdle.io/2026/10/cart-costs.html",
                "summary": "Check the unit price of the foods you already buy.",
                "image_url": "https://i.ibb.co/test2/cart.jpg",
            },
        ],
        [],
    )
    assert "https://news.youdle.io/2026/10/beef-prices.html" in html
    assert "https://news.youdle.io/2026/10/cart-costs.html" in html
    assert html.count("https://i.ibb.co/test1/beef.jpg") == 1
    assert html.count("https://i.ibb.co/test2/cart.jpg") == 1
    assert "Practical details about the grocery prices" in html


def test_missing_image_never_reuses_the_previous_photo():
    mailer = object.__new__(MailchimpCampaign)
    with_image = mailer._format_article_link(
        "Grocery shopping", "https://news.youdle.io/2026/10/first.html",
        image_url="https://i.ibb.co/test/picture.jpg",
    )
    without_image = mailer._format_article_link(
        "Food safety", "https://news.youdle.io/2026/10/second.html",
        image_url="",
    )
    assert "<img" in with_image
    assert "<img" not in without_image
    assert "picture.jpg" not in without_image


def test_original_recall_photo_remains_unchanged():
    mailer = object.__new__(MailchimpCampaign)
    url = "https://blogger.googleusercontent.com/img/b/old-recall.jpg"
    html = mailer._format_recall_link(
        "Food recall alert", "https://news.youdle.io/2026/10/alert.html",
        image_url=url,
    )
    assert url in html
    assert "https://news.youdle.io/2026/10/alert.html" in html


def test_unsafe_image_urls_never_render():
    assert MailchimpCampaign._article_image_html("javascript:alert(1)", "Bad", "https://www.youdle.io/news") == ""
    assert MailchimpCampaign._article_image_html("https://untrusted.invalid/evil.jpg", "Bad", "https://www.youdle.io/news") == ""


def test_public_grocerysos_supabase_article_image_renders():
    url = (
        "https://wziocgpteiozbtgeoplj.supabase.co"
        "/storage/v1/object/public/blog-images/media/test-photo.jpg"
    )
    html = MailchimpCampaign._article_image_html(url, "Aldi savings", "https://news.youdle.io/2026/11/test.html")
    assert url in html
    assert 'alt="Aldi savings"' in html


def test_private_supabase_storage_image_does_not_render():
    url = "https://wziocgpteiozbtgeoplj.supabase.co/storage/v1/object/private/private-photo.jpg"
    assert MailchimpCampaign._article_image_html(url, "Private", "https://news.youdle.io/2026/11/test.html") == ""
