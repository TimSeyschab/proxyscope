from proxyscope.application.processing.headers import header_value, remove_header


def test_header_lookup_is_case_insensitive_and_preserves_value():
    assert header_value({"Content-Type": "Text/Plain"}, "content-type") == "Text/Plain"
    assert header_value({}, "missing") == ""


def test_removal_deletes_all_case_variants_only():
    headers = {"Content-Length": "10", "content-length": "20", "X-Other": "kept"}
    remove_header(headers, "CONTENT-LENGTH")
    remove_header(headers, "CONTENT-LENGTH")
    assert headers == {"X-Other": "kept"}
