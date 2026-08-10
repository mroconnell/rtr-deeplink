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
    if (!signInLink || !userButtonEl) return;
    if (window.Clerk && window.Clerk.user) {
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
      await window.Clerk.load();
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
