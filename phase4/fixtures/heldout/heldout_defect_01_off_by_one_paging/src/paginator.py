"""Pagination utility with offset calculation."""
from typing import Any, List, Dict

def paginate(items: List[Any], page: int, per_page: int) -> Dict[str, Any]:
    """Paginates a list of items using 1-based indexing.
    
    Returns a dict with:
      - items: list of items on this page
      - total_items: total count
      - total_pages: computed total pages
      - page: current page
      - per_page: page size
    """
    if per_page <= 0:
        raise ValueError("per_page must be positive")
    if page <= 0:
        raise ValueError("page must be positive")
        
    total_items = len(items)
    # BUG: Off-by-one error: integer division without ceil when items > 0
    total_pages = total_items // per_page
    
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    
    return {
        "items": items[start_idx:end_idx],
        "total_items": total_items,
        "total_pages": total_pages,
        "page": page,
        "per_page": per_page,
    }
