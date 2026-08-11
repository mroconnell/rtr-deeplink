/* Loads ClerkJS and wires the shared nav sign-in/user-button, on every
 * page of both services (mounted identically at /shared-static on each,
 * same reasoning as deep_link.js's own header comment). Entirely
 * client-side and entirely optional: if CLERK_PUBLISHABLE_KEY isn't set
 * (data-clerk-publishable-key missing/empty on <body>), this does
 * nothing at all -- no script load attempted, nav stays exactly as
 * server-rendered. Any failure past that point (bad key, Clerk down,
 * network error, an API this file assumed wrong) is caught and logged,
 * never left to break the rest of the page -- see this feature's
 * "nothing existing gets gated behind login" design note.
 *
 * Exposes window.RTRClerk = { isSignedIn(), getUserId() } for other
 * page-specific scripts (meeting_page.js, meeting_list.js,
 * saved_items.js) to check auth state without each reaching into
 * window.Clerk directly, and fires a "rtr-clerk-ready" document event
 * once Clerk has finished loading (fired even if unconfigured/failed,
 * so listeners never hang waiting for an event that'll never come).
 */
(function () {
  function markReady() {
    document.dispatchEvent(new CustomEvent("rtr-clerk-ready"));
  }

  const pubKey = document.body.dataset.clerkPublishableKey || "";
  const fapiUrl = document.body.dataset.clerkFapiUrl || "";
  if (!pubKey || !fapiUrl) {
    window.RTRClerk = { isSignedIn: () => false, getUserId: () => null };
    markReady();
    return;
  }

  function loadScript(src, attrs) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.defer = true;
      s.crossOrigin = "anonymous";
      if (attrs) {
        Object.keys(attrs).forEach((k) => s.setAttribute(k, attrs[k]));
      }
      s.onload = resolve;
      s.onerror = () => reject(new Error("script failed to load: " + src));
      document.head.appendChild(s);
    });
  }

  function renderNavAuthState() {
    const signInLink = document.getElementById("clerk-sign-in-link");
    const userButtonEl = document.getElementById("clerk-user-button");
    // "Get Updates" just points at the newsletter signup -- someone with
    // a real account can already get updates (see the account+newsletter
    // auto-subscribe decision in BACKLOG.md), so the link is redundant
    // once signed in. Its divider is hidden alongside it so removing the
    // item doesn't leave an orphaned "|" with nothing after it.
    const getUpdatesItem = document.getElementById("nav-get-updates");
    const getUpdatesDivider = document.getElementById("nav-get-updates-divider");
    const signedIn = !!(window.Clerk && window.Clerk.user);

    if (getUpdatesItem) getUpdatesItem.hidden = signedIn;
    // getUpdatesDivider carries Bootstrap's "d-none d-lg-block" utility
    // classes, which set `display: block !important` at the lg
    // breakpoint -- that beats the plain `hidden` attribute (not
    // !important), so the divider stayed visible even when "hidden" even
    // though Get Updates itself correctly disappeared, leaving two
    // dividers with nothing between them. Setting the inline style
    // directly (also !important) wins regardless of viewport width;
    // removing the inline style on sign-out lets Bootstrap's own
    // responsive classes resume control.
    if (getUpdatesDivider) {
      if (signedIn) {
        getUpdatesDivider.style.setProperty("display", "none", "important");
      } else {
        getUpdatesDivider.style.removeProperty("display");
      }
    }

    if (!signInLink || !userButtonEl) return;
    if (signedIn) {
      signInLink.hidden = true;
      userButtonEl.hidden = false;
      if (!userButtonEl.dataset.mounted) {
        window.Clerk.mountUserButton(userButtonEl);
        userButtonEl.dataset.mounted = "true";
      }
    } else {
      signInLink.hidden = false;
      userButtonEl.hidden = true;
    }
  }

  async function init() {
    try {
      await loadScript("https://" + fapiUrl + "/npm/@clerk/clerk-js@latest/dist/clerk.browser.js", {
        "data-clerk-publishable-key": pubKey,
      });
      // window.Clerk may load as a class (Clerk's current documented
      // pattern: `new Clerk(publishableKey)`) or as an already-
      // auto-instantiated singleton (an older documented pattern: call
      // `.load()` directly, relying on the data-clerk-publishable-key
      // attribute above) depending on exactly which build gets served --
      // handle both rather than assume one.
      if (typeof window.Clerk === "function") {
        window.Clerk = new window.Clerk(pubKey);
      }
      // Deliberately NOT passing `ui: { ClerkUI: window.__internal_ClerkUICtor }`
      // (shown in some Clerk doc examples, tied to a separately-loaded
      // @clerk/ui bundle) -- confirmed live that it's not required, and
      // referencing that internal global immediately after the script
      // "loads" was a real race (the global isn't guaranteed to exist
      // the instant the script's own onload fires), which is what was
      // actually causing Clerk.load() to fail, not a bad key as its own
      // generic error message suggested. Clerk's default built-in UI
      // works fine without it.
      //
      // afterSignOutUrl: real bug fixed 2026-08-11, confirmed live by the
      // user on staging -- with no options object at all, sign-out (via
      // the mounted user button's own menu) left the visitor on Clerk's
      // own generic hosted Account Portal page (a real screenshot showed
      // "guided-bedbug-18.accounts.dev/sign-in", no RTR nav/footer at
      // all) instead of anywhere on this site. Sends them back to the
      // homepage instead. Inferred from Clerk's general documented API
      // surface, not checked against live docs this pass (same caveat as
      // everywhere else this is noted) -- needs a real sign-out on
      // staging to confirm this actually redirects correctly, same
      // "don't claim a fix without a positive example" convention as
      // everywhere else in this repo.
      //
      // signInForceRedirectUrl/signUpForceRedirectUrl: real bug fixed
      // 2026-08-11, reported live by the user -- signing in via the
      // modal opened from the meeting page's own "sign in" prompt
      // (transcribe-form's signed-out copy) dropped them on the
      // homepage afterward, with no confirmation the sign-in (or the
      // transcript request that prompted it) actually worked. Root
      // cause: Clerk's own documented default post-sign-in destination
      // (signInFallbackRedirectUrl) is "/" when nothing else is set --
      // this wasn't a bad guess like the earlier caching false-alarm,
      // it's Clerk's real default, confirmed against current docs.
      // window.location.href at Clerk.load() time is wherever the
      // visitor actually started (the meeting page itself, not "/"),
      // so this keeps them there regardless of which page loaded Clerk.
      // "Force" (not "fallback") is deliberate: this app has no
      // Clerk-managed post-auth redirect_url query param flow to defer
      // to, so always redirecting back to the start page is correct in
      // every case, not just the no-redirect_url fallback case.
      await window.Clerk.load({
        afterSignOutUrl: window.location.origin + "/",
        signInForceRedirectUrl: window.location.href,
        signUpForceRedirectUrl: window.location.href,
      });
    } catch (e) {
      console.error("ClerkJS failed to load -- accounts features unavailable, rest of the site unaffected.", e);
      window.RTRClerk = { isSignedIn: () => false, getUserId: () => null };
      markReady();
      return;
    }

    window.RTRClerk = {
      isSignedIn: () => !!window.Clerk.user,
      getUserId: () => (window.Clerk.user ? window.Clerk.user.id : null),
    };

    renderNavAuthState();
    if (typeof window.Clerk.addListener === "function") {
      window.Clerk.addListener(renderNavAuthState);
    }
    markReady();
  }

  document.addEventListener("DOMContentLoaded", () => {
    const signInLink = document.getElementById("clerk-sign-in-link");
    if (signInLink) {
      signInLink.addEventListener("click", (e) => {
        e.preventDefault();
        if (window.Clerk && typeof window.Clerk.openSignIn === "function") window.Clerk.openSignIn();
      });
    }
    // Inline sign-in mount point (used by saved_items.html's logged-out
    // state) -- mounted once Clerk is ready and only if still signed out.
    const inlineSignIn = document.getElementById("clerk-sign-in");
    if (inlineSignIn) {
      document.addEventListener("rtr-clerk-ready", () => {
        if (window.Clerk && !window.Clerk.user) window.Clerk.mountSignIn(inlineSignIn);
      });
    }
  });

  init();
})();
