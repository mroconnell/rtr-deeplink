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

  // Real bug fixed 2026-08-11: three rounds of Clerk's own documented
  // redirect options (Clerk.load()'s signInForceRedirectUrl/
  // afterSignOutUrl, openSignIn()'s own forceRedirectUrl, and a Clerk
  // Dashboard Component-paths fix) were all confirmed live on staging to
  // still drop the visitor on the homepage after sign-in, for both email
  // and Google -- not a caching false-alarm each time; each fix was
  // verified actually deployed and live-tested. Rather than keep trusting
  // Clerk's internal redirect resolution (whatever is overriding it
  // wasn't identified), this takes control directly with plain JS:
  // markSignInReturnUrl() stashes the current URL in sessionStorage right
  // before any sign-in trigger opens the modal; renderNavAuthState()
  // below checks for it on every Clerk state change (not just the
  // triggering page's own transition into signed-in, but also a fresh
  // page load if Clerk's own navigation won the race and landed
  // somewhere else first) and forces the browser back with
  // window.location.replace() if it's not already there. Self-clearing
  // (removed on read) so it only ever fires once per sign-in.
  const SIGNIN_RETURN_KEY = "rtrSignInReturnUrl";

  // "rtr-clerk-ready" fires on the failure path too (by design -- see the
  // header comment: listeners must never hang waiting for an event that
  // won't come), and ClerkJS's *script* having loaded doesn't mean
  // Clerk.load() succeeded. So window.Clerk can exist, expose every
  // mount* method, and still throw "ClerkJS components are not ready
  // yet" on any of them. Caught live 2026-08-28 as a genuine uncaught
  // page error while verifying WO-65 against a key that rejected the
  // origin. Every mount below checks this flag first.
  let clerkLoaded = false;

  function markSignInReturnUrl() {
    try {
      sessionStorage.setItem(SIGNIN_RETURN_KEY, window.location.href);
    } catch (e) {
      // Private-browsing/storage-disabled: sign-in still works, just
      // without the forced-return safety net.
    }
  }
  window.rtrMarkSignInReturn = markSignInReturnUrl;

  // Standalone /sign-up and /sign-in pages (WO-65). Those exist because
  // Clerk's *mounted* (non-modal) SignIn renders its "No account? Sign
  // up" link at signUpUrl -- default /sign-up on this origin -- and that
  // path used to 404. The modal opened from the nav is unaffected and is
  // deliberately left on Clerk's virtual router; only the mounted
  // components below get explicit signUpUrl/signInUrl.
  //
  // Their post-auth destination can't be window.location.href the way
  // every other trigger's is, or signing up would land the visitor back
  // on the sign-up page. Prefer whatever the page they came *from*
  // stashed (normally /account/saved, stashed by the inline mount there
  // before its "Sign up" link navigated away), and otherwise send them
  // to /account/saved -- the one page that only exists for signed-in
  // visitors. Written back into the stash so maybeForceSignInReturn()
  // handles the redirect uniformly, exactly as it does everywhere else.
  const ACCOUNT_LANDING = "/account/saved";
  const AUTH_PAGE_RE = /\/sign-(in|up)(?:[/?#]|$)/;

  function standaloneAuthDestination() {
    let stashed = null;
    try {
      stashed = sessionStorage.getItem(SIGNIN_RETURN_KEY);
    } catch (e) {
      // Storage disabled -- fall through to the default landing below.
    }
    if (stashed && !AUTH_PAGE_RE.test(stashed)) return stashed;
    const fallback = window.location.origin + ACCOUNT_LANDING;
    try {
      sessionStorage.setItem(SIGNIN_RETURN_KEY, fallback);
    } catch (e) {
      // Same as above -- forceRedirectUrl below still carries it.
    }
    return fallback;
  }

  // Same contract as init()'s own catch: a mount that blows up leaves
  // the surrounding page working and logs, rather than throwing.
  function mountOrIgnore(fn) {
    try {
      fn();
    } catch (e) {
      console.error("Clerk component failed to mount -- rest of the page unaffected.", e);
    }
  }

  function maybeForceSignInReturn(signedIn) {
    if (!signedIn) return false;
    let returnUrl = null;
    try {
      returnUrl = sessionStorage.getItem(SIGNIN_RETURN_KEY);
      sessionStorage.removeItem(SIGNIN_RETURN_KEY);
    } catch (e) {
      return false;
    }
    if (!returnUrl || returnUrl === window.location.href) return false;
    window.location.replace(returnUrl);
    return true;
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
    const signedIn = !!(window.Clerk && window.Clerk.user);
    if (maybeForceSignInReturn(signedIn)) return; // navigating away -- nothing else to do

    const signInLink = document.getElementById("clerk-sign-in-link");
    const userButtonEl = document.getElementById("clerk-user-button");
    // "Get Updates" just points at the newsletter signup -- someone with
    // a real account can already get updates (see the account+newsletter
    // auto-subscribe decision in BACKLOG.md), so the link is redundant
    // once signed in. Its divider is hidden alongside it so removing the
    // item doesn't leave an orphaned "|" with nothing after it.
    const getUpdatesItem = document.getElementById("nav-get-updates");
    const getUpdatesDivider = document.getElementById("nav-get-updates-divider");

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

    clerkLoaded = true;
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
        // Real bug found 2026-08-31: Clerk's openSignIn() *modal* (used
        // here until this fix) has no recovery path when a step
        // transition inside it fails. Confirmed live: password-strategy
        // sign-in from a browser/device Clerk hasn't seen before trips
        // "Client Trust" -- Clerk's anti-credential-stuffing check, on by
        // default for every instance, not something this repo opted
        // into (see the SignIn attempt response's own
        // "client_trust_state": "new" field) -- which demands an
        // email-code second factor. The modal's Radix-based dialog tries
        // to aria-hide its backdrop as part of that step transition while
        // focus is still retained on the (now `disabled`) password input
        // inside it; the browser correctly refuses ("Blocked aria-hidden
        // on an element because its descendant retained focus", caught
        // live in DevTools) and the transition to the second-factor UI
        // never happens. No error, no timeout -- the spinner just spins
        // forever. Because Client Trust only fires for a genuinely new
        // device, this never showed up in ordinary repeat-testing from
        // the same browser.
        //
        // The standalone /sign-in page (mounted below via mountSignIn(),
        // WO-65) has no modal/backdrop at all, so there's nothing for
        // Clerk to aria-hide mid-transition -- confirmed live this
        // sidesteps the hang. Routing the nav link there instead of
        // through openSignIn() fixes this regardless of whether Client
        // Trust (or real per-user MFA, same code path) ends up requiring
        // a second factor, rather than depending on a fix to Clerk's own
        // dialog component.
        //
        // markSignInReturnUrl() (real, deterministic fix from 2026-08-11,
        // see maybeForceSignInReturn() above) still has to fire here and
        // not just rely on /sign-in's own default landing page --
        // without it, standaloneAuthDestination() has nothing stashed and
        // sends the visitor to /account/saved instead of back to
        // whatever page they clicked "Sign in" from. Not preventDefault()
        // -- the href="/sign-in" navigation is now the real mechanism,
        // this just needs to win the race against it, which a synchronous
        // sessionStorage write always does.
        markSignInReturnUrl();
      });
    }
    // Inline sign-in mount point (used by saved_items.html's logged-out
    // state) -- mounted once Clerk is ready and only if still signed out.
    // Marks the return URL up front (this page, /account/saved) since
    // there's no separate click to hook -- the form is already on-screen.
    const inlineSignIn = document.getElementById("clerk-sign-in");
    if (inlineSignIn) {
      document.addEventListener("rtr-clerk-ready", () => {
        if (clerkLoaded && !window.Clerk.user) {
          markSignInReturnUrl();
          mountOrIgnore(() =>
            window.Clerk.mountSignIn(inlineSignIn, {
              forceRedirectUrl: window.location.href,
              // Explicit rather than relying on Clerk's default
              // resolution of this same path -- the default is what
              // silently produced a link to a 404 before /sign-up
              // existed, so it's pinned here so a Clerk-side default
              // change can't re-break it.
              signUpUrl: "/sign-up",
            }),
          );
        }
      });
    }
    // Standalone /sign-up and /sign-in pages -- see
    // standaloneAuthDestination() above for why their redirect target is
    // computed rather than being the current URL.
    const signUpPage = document.getElementById("clerk-sign-up");
    const signInPage = document.getElementById("clerk-sign-in-page");
    if (signUpPage || signInPage) {
      document.addEventListener("rtr-clerk-ready", () => {
        if (!clerkLoaded) return;
        // Already signed in: these two pages have nothing to show, so
        // send them where they were headed instead of rendering an empty
        // page. window.location.replace() keeps /sign-up out of the back
        // history, so "back" doesn't bounce them straight here again.
        if (window.Clerk.user) {
          window.location.replace(standaloneAuthDestination());
          return;
        }
        const dest = standaloneAuthDestination();
        mountOrIgnore(() => {
          if (signUpPage) {
            window.Clerk.mountSignUp(signUpPage, {
              forceRedirectUrl: dest,
              signInUrl: "/sign-in",
            });
          } else {
            window.Clerk.mountSignIn(signInPage, {
              forceRedirectUrl: dest,
              signUpUrl: "/sign-up",
            });
          }
        });
      });
    }
  });

  init();
})();
