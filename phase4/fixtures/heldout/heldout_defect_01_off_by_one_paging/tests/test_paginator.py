import pytest
from src.paginator import paginate

def test_paginate_exact_multiple():
    items = list(range(10))
    res = paginate(items, page=1, per_page=5)
    assert res["total_pages"] == 2
    assert res["items"] == [0, 1, 2, 3, 4]

def test_paginate_partial_remainder():
    items = list(range(11))
    res = paginate(items, page=3, per_page=5)
    # 11 items with 5 per page needs 3 pages (5, 5, 1)
    assert res["total_pages"] == 3
    assert res["items"] == [10]

def test_paginate_empty():
    items = []
    res = paginate(items, page=1, per_page=5)
    assert res["total_pages"] == 0
    assert res["items"] == []

def test_paginate_invalid_arguments():
    with pytest.raises(ValueError):
        paginate([1, 2], page=0, per_page=5)
    with pytest.raises(ValueError):
        paginate([1, 2], page=1, per_page=0)
