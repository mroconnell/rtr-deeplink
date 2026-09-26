"""WO-1085: Meeting Finder reads every tab of a Swagit view page.

Why (2026-09-26): a `/views/{id}` page is the tenant's whole archive, one
tab per body and year, each its own `table#video-table`.
`_parse_swagit_video_table` read only the first table -- the current year
of the first body. Carmel IN's view 1 lists 1,530 meetings in 88 tabs and
19 were read; across all 567 view pages with meetings, 9,622 of 246,945.

`tests/fixtures/swagit/dublin_views_876_all_tabs.html` is a real capture of
Dublin CA's view 876, 2026-09-26, keeping the tab list and all 4 tabs
(City Council 2026/2025, Planning Commission 2026/2025), trimmed to 2 rows
each (see the comment inside it).
"""

from pathlib import Path

from app.platforms.meeting_finder import listing

FIXTURE = (
    Path(__file__).parent / "fixtures" / "swagit" / "dublin_views_876_all_tabs.html"
)
DUBLIN = "https://dublinca.new.swagit.com"


def test_every_tab_of_a_view_page_is_read():
    candidates = listing._parse_swagit_video_table(
        FIXTURE.read_text(), f"{DUBLIN}/views/876/"
    )
    assert [(c.url, c.title, c.date) for c in candidates] == [
        (f"{DUBLIN}/videos/401121", "City Council", "2026-09-15"),
        (f"{DUBLIN}/videos/399711", "City Council", "2026-09-01"),
        (f"{DUBLIN}/videos/364805", "City Council", "2025-12-16"),
        (f"{DUBLIN}/videos/362514", "City Council", "2025-12-02"),
        (f"{DUBLIN}/videos/399384", "Planning Commission", "2026-08-25"),
        (f"{DUBLIN}/videos/391991", "Planning Commission", "2026-06-23"),
        (f"{DUBLIN}/videos/363205", "Planning Commission", "2025-12-09"),
        (f"{DUBLIN}/videos/361620", "Special Planning Commission", "2025-11-19"),
    ]
