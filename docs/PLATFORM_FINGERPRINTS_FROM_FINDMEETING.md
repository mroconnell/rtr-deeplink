# Platform fingerprints from Find Meeting (relay, 2026-10-06)

## What this is and why

The Find Meeting pipeline (repo `rtr-findmeeting`) built one table of platform fingerprints on 2026-10-06. A **fingerprint** is a
short string that tends to appear on one platform's sites: a host, a link path, a query name, a phrase in the page, a meta tag, a
robots.txt line or a sitemap file name. Ryan approved it as a recorded hint on the homepage read. It names a platform; it never
names an owner, and nothing routes on it.

Building it meant reading this repo's recognizers and host lists side by side with Find Meeting's. This note relays what the
comparison found for the rtr-deeplink team. Nothing in this repo was changed except this note and one BACKLOG entry.

## Where the table lives

- The table: `rtr-findmeeting/findmeeting/rules/data/platform_fingerprints.csv` (merged in rtr-findmeeting PR #42). 301 rows:
  255 hints in 52 families (71 UNIQUE, 51 SHARED, 133 WEAK) and 46 exclusions (trap hosts). Each row cites its source.
- How it was built, the class rule, the offline check and its circularity: `rtr-findmeeting/analysis/platform_fingerprints/README.md`.
- Every disagreement between sources: `rtr-findmeeting/analysis/platform_fingerprints/contradictions.csv` (27 rows).
- The six source catalogs, including two read from this repo's origin/main (commit e553069):
  `rtr-findmeeting/analysis/platform_fingerprints/catalogs/` (`deeplink/`, `deeplink_meeting_finder/`, `deeplink_hosts/`).

The class rule: UNIQUE is precision 0.95 or more on 20 or more sites; SHARED is 20 or more sites at precision 0.3 or more; WEAK is
anything less, or not measured. Precision counts labeled sites only (labels from the research file and the coverage registry).

## The headline finding: robots.txt

robots.txt is the best own-domain fingerprint either repo holds, and this repo does not use it for platform identity. Find
Meeting already reads robots.txt for every site, so it costs no request.

| Family | robots.txt line | Labeled sites of the family | Precision | Recall | Unlabeled cached sites that carry it |
|---|---|---|---|---|---|
| CivicPlus | `Disallow: /activedit` | 1,730 | 1.00 | 0.78 | 231 |
| Finalsite | `Allow: /fs/pages/N`, `Disallow: /fs/` | 35 | 1.00 | 0.97 | 1,879 |
| GovOffice | `Disallow: /*guestbook*` | 39 | 0.93 | 1.00 | 448 |

Caution: these rows were chosen from the same cached files and labels they are scored on. The numbers show the rows hold on the
data they came from; they are not an independent test.

## Families and hosts Find Meeting knows that this repo lacks

Checked against this repo's `app/` on origin/main of 2026-10-06 (commit 35db712).

| Host or signal | Family | Where Find Meeting has it | In this repo's `app/` |
|---|---|---|---|
| `cablecast.net` | Cablecast | host_families.csv | No |
| `civicmedia.us`, `civicmedia.com` | CivicMedia | host_families.csv | No (only `civplus.tikiliveapi.com`) |
| `boardbook.org` | BoardBook | host_families.csv | No |
| `neola.com` | Neola (policy site, not meetings) | host_families.csv | No |
| `govoffice.com`, `govoffice3.com` | GovOffice | host_families.csv | Only in `scripts/cms_fingerprint.py` |
| `revize.com` | Revize | host_families.csv | Only in `scripts/cms_fingerprint.py` |
| `goboarddocs.com` | BoardDocs | fingerprint table (hint) | No (not in `app/` or `scripts/`) |
| robots.txt template lines | CivicPlus, Finalsite, GovOffice, CivicLive and SharpSchool, WordPress | fingerprint table | No robots.txt fingerprints at all |
| sitemap file names | FunctionalGov (`wp-sitemap-taxonomies-document_type-N.xml`), WordPress and Yoast | fingerprint table | Only `/wp-sitemap.xml` as a place to start |
| Apptegy, Edlio and SharpSchool site-builder signals (`aptg.co`, `edl.io`, `/cms/One.aspx`) | site builders | fingerprint table | No (`scripts/cms_fingerprint.py` has no rule for them) |

## Families and hosts this repo knows that Find Meeting's host list lacks

Find Meeting's `host_families.csv` was not changed (it drives skips and crawl delays there). The fingerprint table now carries most
of these as WEAK hints.

| Group | Hosts | In the fingerprint table |
|---|---|---|
| Vendors with an adapter | `clerkshq.com`, `spectrumstream.com`, `*-harmony.sliq.net`, `12milesout.com`, `open.media`, `ompnetwork.org`, `peg.tv`, `legistar.council.nyc.gov`, `wistia.com` | Yes |
| Single-government or state hosts | `tvw.org`, `azleg.gov`, `assembly.ca.gov`, `senate.ca.gov`, `seattlechannel.org`, `auroratv.org`, `lims.minneapolismn.gov`, `chicityclerkelms.chicago.gov`, `apps.tampagov.net`, `slc.gov`, `utah.gov` | No (they name one government, not a platform family) |
| No adapter | `novusagenda.com`, `agendasuite.org`, `portal.laserfiche.com` | Yes |
| No adapter | `video.ibm.com` | No |
| Web-host hint | `granicusgovaccess.net` | Yes (family `govaccess`) |
| Variant host | `community-ca.highbond.com` | Yes |
| Website builders | OpenCities, Town Web, WordPress, Municipal Impact, Finalsite, Functional Gov, CourseVector, `govoffice2.com` | Yes |
| Website builders | Indiana towns portal, West Virginia portal, Streamline | Streamline only |

## The eight hosts asked about

| Host | Family | In this repo's `app/` | In Find Meeting's host_families.csv | In the fingerprint table |
|---|---|---|---|---|
| `goboarddocs.com` | BoardDocs | No | No | Hint |
| `isilive.ca` (`video.isilive.ca`, `cdn1.isilive.ca`) | eScribe video (iSiLIVE) | Yes (`direct_file.py`) | No | Hint (host and asset) |
| `peg.tv` | TelVue | Yes (`base.py:494`) | No | Hint |
| `diligent.community` | Diligent (filed as CivicWeb here) | Yes (`base.py`: bare host is corporate; tenants recognized) | Yes | Hint for tenants; the bare host is an exclusion |
| `highbond.com` (`community.highbond.com`, `community-ca.highbond.com`) | Diligent (CivicWeb here) | Yes (`base.py:465-469`) | `community.highbond.com` only | Hint (both) |
| `granicusgovaccess.net` | Granicus GovAccess website | Yes (`host_recognition.py:216`, web-host hint only) | No | Hint (family `govaccess`) |
| `govaccess.org` | Granicus GovAccess website | No (one script only) | No | Hint (family `govaccess`) |
| `getsuiteone.com` | SuiteOne | Named in a comment only (`base.py:228`: the bare `suiteonemedia.com` redirects there, a rebrand) | No | Listed; it is the vendor's own site, so it names no tenant |

## Contradictions that touch this repo

The numbers are row ids in `contradictions.csv`.

| Id | Topic | The disagreement | What Find Meeting's data says |
|---|---|---|---|
| 1 | `/Portal/MeetingInformation.aspx` | `platform_signatures.csv:8` and `civicweb.py` say CivicWeb; `host_recognition.py:241` and the wo147/wo268 scripts say CivicClerk | 198 CivicWeb sites and 141 Diligent sites (same software); no CivicClerk site. Likely a mislabel in `host_recognition.py`. |
| 2 | `/Archive.aspx` (`?AMID=`) | `host_recognition.py` says Legistar; `direct_file.py` treats it as a CivicPlus file link | 126 CivicPlus homepages link their own `/Archive.aspx`; 0 others. |
| 3 | `/Meeting.aspx` | eScribe | AgendaOnline (`agendaonline.net`) uses the same name; require `Id=` or `Agenda=`. |
| 4 | Diligent hosts | Here: CivicWeb. Find Meeting: its own family `diligent` | Same software either way; the host label `community` is 740 Diligent sites to 5 others. |
| 5 | `civicplus.com` | Here: both a meeting platform and a website builder. Find Meeting: a website builder only | The footer credit to `www.civicplus.com` is the commonest CivicPlus string; it is a credit, not a tenant. |
| 7 | bare `clerkshq.com` | `base.py`/`registry.py`: a shared tenant host. `wo147_access_ladder_sweep.py:278`: a marketing apex, never a tenant | Not measured. |
| 8 | bare `cablecast.tv`, `telvue.com`, `champds.com` | `registry.py`: shared hosts. The wo147 script list: marketing apexes | Not measured. |
| 9 | Vendor host vs shared host | Find Meeting calls 11 families `vendor_tenant`; 16 of this repo's 37 `MULTI_GOV_HOSTS` match one of its suffixes | A host can name a platform without naming a government. |
| 11 | `granicus.com` links | `platform_signatures` granicus-vendor-host: hit 1.0, FP 0.038 (n=10) | A homepage link to granicus.com is SHARED 0.68: OpenCities and GovAccess sites link it, and BuiltWith's "Granicus" tag is GovDelivery. |
| 25 | `host_recognition.py` comment | The comment says four path-only entries | The code has five. |

## Shared hosts: gaps in `MULTI_GOV_HOSTS`

A blank-match (whole-host) pin is refused only on a `MULTI_GOV_HOSTS` host. That set holds 37 exact host names.

**Unprotected YouTube aliases.** `base.py:1034-1038` recognizes these as YouTube, but they are not in `MULTI_GOV_HOSTS`, so a
whole-host pin on one would still load. Each has 0 pins today.

- `music.youtube.com`
- `youtube-nocookie.com`
- `www.youtube-nocookie.com`
- `www.youtu.be`

**69 hosts carry pins for two or more governments but are not in `MULTI_GOV_HOSTS`.** Counted on origin/main of 2026-10-06
(commit 35db712) from `app/utils/jurisdiction_data/tenant_overrides.csv` and `registry.MULTI_GOV_HOSTS`. A blank-match pin on any
of them would still load. 7 of them already mix blank-match and match pins.

| Group | Count of 69 |
|---|---|
| Cablecast station hosts | 62 |
| Granicus tenants | 3 |
| `www.utah.gov` (Utah Public Meeting Notice) | 1 |
| `video.isilive.ca` | 1 |
| `hamburgny.new.swagit.com` | 1 |
| `trms.northmetrotv.com` | 1 |
| Total | 69 |

Every host, with the count of governments its pins name, its blank-match pins and its match pins:

| Host | Governments pinned | Blank-match pins | Match pins |
|---|---|---|---|
| www.utah.gov | 70 | 0 | 139 |
| video.isilive.ca | 14 | 0 | 15 |
| reflect-northwest-access.cablecast.tv | 11 | 0 | 15 |
| reflect-lpctv.cablecast.tv | 8 | 0 | 8 |
| gnat.cablecast.tv | 7 | 0 | 7 |
| reflect-lockport.cablecast.tv | 7 | 0 | 11 |
| reflect-miami-valley-cc.cablecast.tv | 7 | 0 | 19 |
| reflect-bloomfield-community.cablecast.tv | 6 | 0 | 12 |
| reflect-vod-cmac.cablecast.tv | 6 | 0 | 13 |
| reflect-ctsbtv.cablecast.tv | 5 | 0 | 5 |
| reflect-origin-1119.cablecast.tv | 5 | 0 | 8 |
| reflect-tvctv.cablecast.tv | 5 | 0 | 6 |
| reflect-vod-lmctv.cablecast.tv | 5 | 0 | 11 |
| reflect-cumberlandcounty-govt.cablecast.tv | 4 | 0 | 6 |
| reflect-qctv.cablecast.tv | 4 | 0 | 6 |
| reflect-tacm.cablecast.tv | 4 | 0 | 6 |
| catv.cablecast.tv | 3 | 0 | 3 |
| nevco.granicus.com | 3 | 1 | 2 |
| reflect-city-of-salinaks.cablecast.tv | 3 | 0 | 7 |
| reflect-citylink-siouxfalls.cablecast.tv | 3 | 0 | 7 |
| reflect-easthamptonmediatv.cablecast.tv | 3 | 0 | 7 |
| reflect-geauga-gtv.cablecast.tv | 3 | 0 | 5 |
| reflect-mctv-midland-mi.cablecast.tv | 3 | 0 | 3 |
| reflect-midvalley.cablecast.tv | 3 | 0 | 3 |
| reflect-origin-1440.cablecast.tv | 3 | 0 | 3 |
| reflect-origin-995.cablecast.tv | 3 | 0 | 3 |
| reflect-sttammany.cablecast.tv | 3 | 0 | 11 |
| reflect-surryco-nc.cablecast.tv | 3 | 0 | 3 |
| reflect-vod-northtv.cablecast.tv | 3 | 0 | 3 |
| reflect-vod-scctv.cablecast.tv | 3 | 0 | 3 |
| reflect-westernhills.cablecast.tv | 3 | 0 | 3 |
| burbank.granicus.com | 2 | 1 | 1 |
| dixon-ca.granicus.com | 2 | 1 | 1 |
| hamburgny.new.swagit.com | 2 | 1 | 1 |
| m-pact.cablecast.tv | 2 | 0 | 2 |
| reflect-access12tv.cablecast.tv | 2 | 0 | 2 |
| reflect-bethelpark-cable.cablecast.tv | 2 | 1 | 1 |
| reflect-catv-erie.cablecast.tv | 2 | 0 | 6 |
| reflect-champaign.cablecast.tv | 2 | 0 | 4 |
| reflect-cityofalbertlea.cablecast.tv | 2 | 0 | 4 |
| reflect-cityofdayton.cablecast.tv | 2 | 0 | 4 |
| reflect-cityofwillmar.cablecast.tv | 2 | 0 | 4 |
| reflect-communitytv.cablecast.tv | 2 | 0 | 6 |
| reflect-forestlake.cablecast.tv | 2 | 0 | 4 |
| reflect-guilfordctv.cablecast.tv | 2 | 0 | 4 |
| reflect-helena-civic.cablecast.tv | 2 | 0 | 4 |
| reflect-independence-tv-mi.cablecast.tv | 2 | 0 | 2 |
| reflect-lakefront-leesburgflorida.cablecast.tv | 2 | 0 | 4 |
| reflect-newport.cablecast.tv | 2 | 0 | 2 |
| reflect-niagarafallsosc.cablecast.tv | 2 | 0 | 2 |
| reflect-npctv.cablecast.tv | 2 | 0 | 2 |
| reflect-ontv.cablecast.tv | 2 | 1 | 1 |
| reflect-pcta-fountainvalley-vod.cablecast.tv | 2 | 0 | 6 |
| reflect-rehobothtv.cablecast.tv | 2 | 0 | 3 |
| reflect-smsu.cablecast.tv | 2 | 0 | 4 |
| reflect-southborough.cablecast.tv | 2 | 0 | 4 |
| reflect-stcloudcity.cablecast.tv | 2 | 0 | 4 |
| reflect-swampscottma.cablecast.tv | 2 | 0 | 6 |
| reflect-tvschedule-cityofmadison.cablecast.tv | 2 | 0 | 6 |
| reflect-two-harbors.cablecast.tv | 2 | 1 | 2 |
| reflect-video-ondemand-cpsd.cablecast.tv | 2 | 0 | 2 |
| reflect-vod-athol.cablecast.tv | 2 | 0 | 2 |
| reflect-vod-eagan.cablecast.tv | 2 | 0 | 4 |
| reflect-vod-fcgov.cablecast.tv | 2 | 0 | 10 |
| reflect-vod-salem.cablecast.tv | 2 | 0 | 4 |
| reflect-vsctv.cablecast.tv | 2 | 0 | 3 |
| reflect-watchncam.cablecast.tv | 2 | 0 | 2 |
| reflect-wausau-wi.cablecast.tv | 2 | 0 | 2 |
| trms.northmetrotv.com | 2 | 0 | 2 |

Two smaller items from the same catalog:

- `livestream.telvue.com` is in a script's shared list and the identity gate's skip list, but not in `MULTI_GOV_HOSTS` (1 pin).
- `MULTI_GOV_HOSTS` matches exact names, while `tenant_key.py` matches any `*harmony.sliq.net`. A new server such as `sg003` would
  be keyed but not protected.

## Recommendation

1. Settle contradiction 1 (`/Portal/MeetingInformation.aspx`): the data says CivicWeb.
2. Decide whether the 69 hosts and the four YouTube aliases belong in `MULTI_GOV_HOSTS`, or whether the rule should key on a shape
   (for example any `reflect-*.cablecast.tv`) instead of exact names.
3. Consider the robots.txt lines above as a cheap own-domain CivicPlus, Finalsite and GovOffice signal for Meeting Finder's Identify step.
4. Consider adding `goboarddocs.com` to the BoardDocs recognizer, after a live check.

None of this was tested live. Each item needs the usual real-URL check before any code change.
