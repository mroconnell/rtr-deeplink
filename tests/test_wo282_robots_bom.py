"""scripts/wo282_recon.py robots readers (live via meeting_finder/start.py) must not lose a
first line that starts with a UTF-8 byte order mark."""

from scripts.wo282_recon import parse_crawl_delay, parse_robots


def test_parse_robots_reads_a_bom_first_line():
    assert parse_robots("﻿Disallow: /\r\n")["disallow_paths"] == ["/"]
    assert parse_robots("﻿Sitemap: https://a.example/s.xml")["sitemap_urls"] == [
        "https://a.example/s.xml"
    ]
    assert parse_robots("﻿User-agent: *\r\nDisallow: /")["disallow_paths"] == ["/"]


def test_parse_crawl_delay_reads_a_bom_first_line():
    assert parse_crawl_delay("﻿Crawl-delay: 9") == 9.0
