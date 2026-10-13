# Drip-conflict decisions (drip Mac, 2026-10-12)

**What was done.** For each of the 31 conflicting addresses (30 US, 1 Canada), the drip Mac made one YouTube metadata call (channel name, description and recent titles), 200 seconds apart, and ran the drip's identity check against both candidate governments.

**Decision.** `keep_owner` for all 31, per Ryan's rule relayed by the Conductor. Nothing was moved or written to the drip list.

**What the check found** (see `decisions.csv`, column `flag_for_review`).
- The identity check could not tell the two governments apart for any pair of paired districts (Helena, Laurel, Polson, Missoula, Culbertson and so on). Shared channels like "Helena MT schools" serve both.
- Some addresses are not either government's own channel: state associations and vendors (Minnesota School Boards Association, WSSDA, TED-Ed, TeacherEase, MAMH, IndianaCommissions, Oklahoma State Department of Education). They are flagged. Consider removing them from the drip list.
- 8 addresses returned no data (unavailable or empty), also flagged.
- One real name match: Lapeer County MI (channel "County of Lapeer Michigan") supports the listed owner over Marathon Township.
