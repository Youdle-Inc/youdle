from pathlib import Path

def test_no_legacy_imgbb_upload_in_graph():
    text = Path("blog_post_graph.py").read_text()
    assert "upload_image_to_imgbb(" not in text
    assert "folder=\"media\"" in text
    assert "Skipped photo-less draft" in text
    assert 'url_lookup.get(post_id, "")' in text

def test_repair_scope_is_exactly_nine_ids():
    from scripts.repair_oct27_gemini_article_images import APPROVED
    assert len(APPROVED) == 9
    assert len({a[0] for a in APPROVED}) == 9
    assert all(len(row)==4 for row in APPROVED)
