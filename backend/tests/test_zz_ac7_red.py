def test_deliberately_red():
    """AC7 (T-059): a red test must turn CI red and block CD. Draft branch only, never merged."""
    assert False, "intentional failure for T-059 AC7"
