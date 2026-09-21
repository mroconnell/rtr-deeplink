"""Full Context entries on the jurisdiction hub (`/j/{slug}`) and state
page (`/state/{slug}`) -- WO-947 (Ryan: "a page like this that is related
to Indianapolis would also appear under the Indianapolis hub, right? And
Indiana?"). Covers crud.list_context_entries_for_pages() and its wiring
into get_jurisdiction_hub_data()/get_state_page_data(), plus the rendered
"Seen on social media" section on both pages.

Real DB integration against the shared SQLite fixture, same pattern as
tests/test_jurisdiction_hubs.py / tests/test_state_pages.py /
tests/test_hub_inclusion_rule.py (read first). Every jurisdiction seeded
here is a real, unambiguous place no other test file uses (checked by
grep before writing this file), so hub/state page counts stay stable
regardless of test order: Walnut Creek, CA (government A) and
Pleasanton, CA (government B, same state, different government -- the
hub-exclusion case) and Twin Falls, ID (government C, different state --
the state-exclusion case).
"""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import update

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage
from archive.utils.context_links import parse_social_url
from archive.utils.jurisdiction_format import jurisdiction_hub_slug

client = TestClient(archive.main.app)


def _payload(external_id, url, *, jurisdiction, title, platform="granicus"):
    return {
        "platform": platform,
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": "2016-03-01",  # matches test_hub_inclusion_rule.py's own
        # convention: old enough to never be a newest-first pick ahead of
        # another test file's page.
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed_page(external_id, url, **kwargs) -> dict:
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result


async def _set_identity(slug: str, gov_id) -> None:
    """Forces an un-keyed identity the resolver's own enrichment would not
    reliably produce from a payload alone -- same technique and same
    reasoning as tests/test_hub_inclusion_rule.py's own _set_identity()."""
    async with async_session() as session:
        await session.execute(
            update(MeetingPage).where(MeetingPage.slug == slug).values(gov_id=gov_id)
        )
        await session.commit()


async def _publish_entry_for(page_id: int, *, title=None, status="published") -> dict:
    suffix = uuid.uuid4().hex[:16]
    result = await crud.save_context_entry(
        "user_ctx_hub_state_test",
        social=parse_social_url(f"https://example.com/context-on-hubs-test/{suffix}"),
        summary="A clip cited on a hub/state page test.",
        title=title,
        meeting_page_id=page_id,
        t_seconds=5,
        match_kind="exact",
        status=status,
    )
    assert "ok" in result, result
    return result["ok"]


# --- crud: list_context_entries_for_pages() + hub/state wiring -------------


async def test_entry_shows_on_its_own_governments_hub_not_a_different_one():
    wc = await _seed_page(
        f"granicus:hub-wc-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hub/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek City Council",
    )
    await _seed_page(
        f"granicus:hub-pl-{uuid.uuid4().hex[:8]}",
        f"https://pleasantonca.granicus.com/hub/{uuid.uuid4().hex[:8]}",
        jurisdiction="Pleasanton, CA",
        title="Pleasanton City Council",
    )
    entry = await _publish_entry_for(wc["page_id"], title="Walnut Creek clip")

    wc_hub = await crud.get_jurisdiction_hub_data("walnut-creek-ca")
    assert wc_hub is not None
    wc_ids = {e["id"] for e in wc_hub["context_entries"]}
    assert entry["id"] in wc_ids

    pl_hub = await crud.get_jurisdiction_hub_data("pleasanton-ca")
    assert pl_hub is not None
    pl_ids = {e["id"] for e in pl_hub["context_entries"]}
    assert entry["id"] not in pl_ids


async def test_entry_shows_on_its_state_page_not_a_different_state():
    wc = await _seed_page(
        f"granicus:hubstate-wc-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubstate/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek City Council (state test)",
    )
    await _seed_page(
        f"granicus:hubstate-tf-{uuid.uuid4().hex[:8]}",
        f"https://twinfallsid.granicus.com/hubstate/{uuid.uuid4().hex[:8]}",
        jurisdiction="Twin Falls, ID",
        title="Twin Falls City Council",
    )
    entry = await _publish_entry_for(wc["page_id"], title="California clip")

    ca = await crud.get_state_page_data("CA")
    assert ca is not None
    ca_ids = {e["id"] for e in ca["context_entries"]}
    assert entry["id"] in ca_ids

    idaho = await crud.get_state_page_data("ID")
    # Idaho may or may not already have pages from another test file, but
    # this specific entry must never appear there.
    if idaho is not None:
        idaho_ids = {e["id"] for e in idaho["context_entries"]}
        assert entry["id"] not in idaho_ids


async def test_draft_entry_never_shows_on_a_hub():
    wc = await _seed_page(
        f"granicus:hubdraft-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubdraft/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek draft test",
    )
    entry = await _publish_entry_for(wc["page_id"], title="Draft clip", status="draft")

    hub = await crud.get_jurisdiction_hub_data("walnut-creek-ca")
    assert hub is not None
    assert entry["id"] not in {e["id"] for e in hub["context_entries"]}


async def test_hidden_entry_never_shows_on_a_hub():
    wc = await _seed_page(
        f"granicus:hubhidden-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubhidden/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek hidden test",
    )
    entry = await _publish_entry_for(wc["page_id"], title="Hidden clip")
    await crud.set_context_entry_status(entry["id"], "hidden")

    hub = await crud.get_jurisdiction_hub_data("walnut-creek-ca")
    assert hub is not None
    assert entry["id"] not in {e["id"] for e in hub["context_entries"]}


async def test_orphaned_entry_never_shows_on_a_hub():
    # Same hand-crafted-orphan shape tests/test_context_entries.py's own
    # test_public_list_excludes_drafts_hidden_and_orphans uses: "published"
    # in the DB with no real meeting joinable. Neither writer can actually
    # produce this on its own -- the INNER JOIN in list_context_entries_
    # for_pages() must exclude it regardless of how it got there.
    from archive.db.models import ContextEntry

    async with async_session() as session:
        orphan = ContextEntry(
            social_url=f"https://example.com/orphan-hub-{uuid.uuid4().hex}",
            social_url_key=f"url:https://example.com/orphan-hub-{uuid.uuid4().hex}",
            network="other",
            summary="An orphaned published row.",
            meeting_page_id=None,
            status="published",
        )
        session.add(orphan)
        await session.commit()
        orphan_id = orphan.id

    hub = await crud.get_jurisdiction_hub_data("walnut-creek-ca")
    assert hub is not None
    assert orphan_id not in {e["id"] for e in hub["context_entries"]}


async def test_hub_context_entries_limit_and_order():
    wc = await _seed_page(
        f"granicus:hublimit-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hublimit/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek limit test",
    )
    entries = [
        await _publish_entry_for(wc["page_id"], title=f"Limit clip {i}")
        for i in range(crud.HUB_CONTEXT_ENTRIES + 2)
    ]
    hub = await crud.get_jurisdiction_hub_data("walnut-creek-ca")
    assert hub is not None
    shown = hub["context_entries"]
    my_ids = {e["id"] for e in entries}
    my_shown = [e for e in shown if e["id"] in my_ids]
    # At most HUB_CONTEXT_ENTRIES of these are visible at all (there may
    # be other tests' entries also on this hub, newer or older).
    assert len(my_shown) <= crud.HUB_CONTEXT_ENTRIES
    # Whichever of mine are shown, they're in newest-published-first order.
    assert my_shown == sorted(
        my_shown, key=lambda e: (e["published_at"], e["id"]), reverse=True
    )
    # The three newest of my own entries are the ones that made it in
    # (published_at is sticky and set at save time here, in creation
    # order, so `entries[-1]` is the newest).
    newest_ids = [e["id"] for e in entries[::-1][: crud.HUB_CONTEXT_ENTRIES]]
    assert {e["id"] for e in my_shown} == set(newest_ids)


async def test_state_context_entries_limit_respected():
    wc = await _seed_page(
        f"granicus:statelimit-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/statelimit/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek state-limit test",
    )
    for i in range(crud.STATE_CONTEXT_ENTRIES + 2):
        await _publish_entry_for(wc["page_id"], title=f"State limit clip {i}")
    ca = await crud.get_state_page_data("CA")
    assert ca is not None
    assert len(ca["context_entries"]) <= crud.STATE_CONTEXT_ENTRIES


async def test_topic_view_never_shows_context_entries_on_hub_or_state():
    wc = await _seed_page(
        f"granicus:hubtopic-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubtopic/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek topic-view test",
    )
    await _publish_entry_for(wc["page_id"], title="Topic view clip")

    hub_topic = await crud.get_jurisdiction_hub_data(
        "walnut-creek-ca", topic_slug="housing-development"
    )
    assert hub_topic is not None
    assert hub_topic["context_entries"] == []

    state_topic = await crud.get_state_page_data("CA", topic_slug="housing-development")
    assert state_topic is not None
    assert state_topic["context_entries"] == []


async def test_text_coincidence_does_not_pull_an_unrelated_entry_into_a_hub():
    """The WO-256 contamination case, for Full Context: an un-keyed page
    on a MULTI_GOV_HOSTS host whose stored jurisdiction TEXT happens to
    read "Walnut Creek, CA" must not put its cited entry on Walnut
    Creek's real hub -- text is a coincidence, page-set membership is
    not. Models tests/test_hub_inclusion_rule.py's own contamination
    case."""
    # A real, keyed Walnut Creek page, so the hub genuinely exists.
    await _seed_page(
        f"granicus:hubcontam-real-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubcontam/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek real meeting",
    )
    # An unrelated YouTube video whose stored text coincidentally matches.
    contaminant = await _seed_page(
        f"youtube:hubcontam-{uuid.uuid4().hex[:8]}",
        f"https://www.youtube.com/watch?v={uuid.uuid4().hex[:11]}",
        jurisdiction="Walnut Creek, CA",
        title="Unrelated video, coincidental text match",
        platform="youtube",
    )
    await _set_identity(contaminant["slug"], "rtr:unknown:www.youtube.com")
    entry = await _publish_entry_for(
        contaminant["page_id"], title="Contamination-check clip"
    )

    hub = await crud.get_jurisdiction_hub_data("walnut-creek-ca")
    assert hub is not None
    assert entry["id"] not in {e["id"] for e in hub["context_entries"]}


# --- pages: /j/{slug} and /state/{slug} HTML -------------------------------


def _section_html(page_text: str) -> str | None:
    marker = 'class="context-mentions"'
    start = page_text.find(marker)
    if start == -1:
        return None
    # Back up to the <section start, forward to its own </section>.
    section_start = page_text.rfind("<section", 0, start)
    section_end = page_text.find("</section>", start)
    return page_text[section_start : section_end + len("</section>")]


async def test_hub_page_renders_the_section_with_headline_link_and_badge():
    wc = await _seed_page(
        f"granicus:hubpage-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubpage/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek hub-page render test",
    )
    entry = await _publish_entry_for(wc["page_id"], title="Hub page render headline")

    response = client.get("/j/walnut-creek-ca")
    assert response.status_code == 200
    assert "Seen on social media" in response.text
    section = _section_html(response.text)
    assert section is not None
    assert (
        f'<a href="{entry["permalink"]}" class="context-mentions-title">Hub page render headline</a>'
        in section
    )
    assert 'class="context-match-badge context-match-exact"' in section
    # No outbound social link inside the section -- "Original post on..."
    # is plain text, never a link (one outbound link lives on the entry
    # page itself, not here).
    assert f'href="{entry["social_url"]}"' not in section


async def test_hub_page_omits_the_government_link_inside_the_section():
    wc = await _seed_page(
        f"granicus:hubpagegov-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubpagegov/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek gov-link omit test",
    )
    await _publish_entry_for(wc["page_id"], title="Gov link omit headline")

    response = client.get("/j/walnut-creek-ca")
    section = _section_html(response.text)
    assert section is not None
    assert 'href="/j/walnut-creek-ca"' not in section


async def test_state_page_shows_the_government_link_inside_the_section():
    wc = await _seed_page(
        f"granicus:statepagegov-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/statepagegov/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek state gov-link test",
    )
    await _publish_entry_for(wc["page_id"], title="State gov link headline")

    response = client.get("/state/california")
    assert response.status_code == 200
    section = _section_html(response.text)
    assert section is not None
    assert 'href="/j/walnut-creek-ca"' in section


async def test_summary_fallback_link_text_is_escaped():
    wc = await _seed_page(
        f"granicus:hubxss-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubxss/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek escaping test",
    )
    suffix = uuid.uuid4().hex[:16]
    result = await crud.save_context_entry(
        "user_ctx_hub_state_test",
        social=parse_social_url(f"https://example.com/context-on-hubs-test/{suffix}"),
        summary="Innocent text <script>alert(1)</script> more text, well past ninety characters so truncation still applies here too.",
        meeting_page_id=wc["page_id"],
        t_seconds=5,
        match_kind="exact",
        status="published",
    )
    assert "ok" in result

    response = client.get("/j/walnut-creek-ca")
    section = _section_html(response.text)
    assert section is not None
    assert "<script>alert(1)</script>" not in section
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in section


async def test_zero_entries_renders_no_section_at_all():
    # A fresh, otherwise-unused, obviously-synthetic government name --
    # not a real place, so jurisdiction_enrich() can't assign it a real
    # gov_id, and _hub_identity() falls back to jurisdiction_hub_slug()
    # on the raw string exactly as given, so the slug below is
    # predictable rather than a guess.
    unique_city = f"Contextlesston{uuid.uuid4().hex[:6]}"
    await _seed_page(
        f"granicus:hubzero-{uuid.uuid4().hex[:8]}",
        f"https://contextlesston.granicus.com/hubzero/{uuid.uuid4().hex[:8]}",
        jurisdiction=f"{unique_city}, ZZ",
        title=f"{unique_city} zero-entry test",
    )
    hub_slug = jurisdiction_hub_slug(f"{unique_city}, ZZ")

    response = client.get(f"/j/{hub_slug}")
    assert response.status_code == 200
    assert "Seen on social media" not in response.text
    assert "context-mentions" not in response.text


async def test_hub_page_still_200s_when_context_check_raises(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated context_entries failure")

    monkeypatch.setattr(crud, "list_context_entries_for_pages", _boom)

    wc = await _seed_page(
        f"granicus:hubraise-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/hubraise/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek raise-guard test",
    )
    await _publish_entry_for(wc["page_id"], title="Raise guard headline")

    response = client.get("/j/walnut-creek-ca")
    assert response.status_code == 200
    assert "Seen on social media" not in response.text


async def test_state_page_still_200s_when_context_check_raises(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated context_entries failure")

    monkeypatch.setattr(crud, "list_context_entries_for_pages", _boom)

    wc = await _seed_page(
        f"granicus:stateraise-{uuid.uuid4().hex[:8]}",
        f"https://walnutcreekca.granicus.com/stateraise/{uuid.uuid4().hex[:8]}",
        jurisdiction="Walnut Creek, CA",
        title="Walnut Creek state raise-guard test",
    )
    await _publish_entry_for(wc["page_id"], title="State raise guard headline")

    response = client.get("/state/california")
    assert response.status_code == 200
