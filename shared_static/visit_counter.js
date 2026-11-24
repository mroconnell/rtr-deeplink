/* Counts this browser's visits to the site in the last 30 days and tells
 * GA (2026-11-24).
 *
 * Why: GA4's own reports give "returning users" but not "users who came 2
 * or more times this month" without a BigQuery export. Ryan wants that
 * number to size the regular-visitor pool. This keeps the count in the
 * visitor's own browser (localStorage, never sent anywhere but GA) and
 * sends one event per visit:
 *
 *   visit_start {visits_30d: "1" | "2" | "3" | "4" | "5+"}
 *
 * plus a GA user property visitor_type = "new_30d" | "repeat_30d" (2 or
 * more visits in 30 days). Both need registering as custom dimensions in
 * the GA property before they show up in reports.
 *
 * A "visit" starts after 30 minutes with no page load, matching GA's own
 * session timeout. Window.RTRVisits.count30d exposes the number for a
 * later on-page prompt. Storage blocked (private windows, many bots):
 * nothing is sent, and the page is unaffected.
 */
(function () {
  const KEY = "rtrVisits";
  const VISIT_GAP_MS = 30 * 60 * 1000;
  const WINDOW_MS = 30 * 24 * 60 * 60 * 1000;
  const MAX_STARTS = 60;

  function bucket(n) {
    return n >= 5 ? "5+" : String(n);
  }

  function run(now) {
    let data;
    try {
      data = JSON.parse(localStorage.getItem(KEY) || "null");
    } catch (e) {
      data = null;
    }
    if (!data || !Array.isArray(data.starts)) data = { starts: [], last: 0 };

    const isNewVisit = !data.last || now - data.last > VISIT_GAP_MS;
    if (isNewVisit) data.starts.push(now);
    data.starts = data.starts.filter((t) => now - t < WINDOW_MS).slice(-MAX_STARTS);
    data.last = now;

    try {
      localStorage.setItem(KEY, JSON.stringify(data));
    } catch (e) {
      return null; // Can't remember visits here: report nothing.
    }

    const count = data.starts.length;
    window.RTRVisits = { count30d: count };
    if (isNewVisit) {
      if (typeof window.gtag === "function") {
        window.gtag("set", "user_properties", {
          visitor_type: count >= 2 ? "repeat_30d" : "new_30d",
        });
      }
      if (typeof window.trackEvent === "function") {
        window.trackEvent("visit_start", { visits_30d: bucket(count) });
      }
    }
    return { count: count, isNewVisit: isNewVisit };
  }

  window.RTRVisitCounter = { run: run, bucket: bucket };
  run(Date.now());
})();
