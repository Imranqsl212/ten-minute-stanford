from ten_minute_stanford.fetch import looks_like_authentication_page


def test_stanford_login_interstitial_is_rejected() -> None:
    html = "<title>Stanford Login</title>Loading login session information"
    assert looks_like_authentication_page(html)
    assert looks_like_authentication_page("public", "https://login.stanford.edu/idp")
    assert not looks_like_authentication_page("<title>Explore Courses</title>")
