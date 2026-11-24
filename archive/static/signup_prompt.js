/* Free-account prompt for signed-out visitors (2026-11-24).
 *
 * Why: until now "Save this meeting" and "Save this search" were only
 * rendered for signed-in visitors, so a new visitor never learned that a
 * free account exists or what it gives them. GA, Oct 25 - Nov 23: /sign-up
 * had 0 views and save_meeting had 0 events. The buttons now render for
 * everyone (meeting_page.html, meeting_list.html); a signed-out click opens
 * this short box instead of calling the save API.
 *
 * The box says what the account is for, then sends the visitor to the
 * existing /sign-up or /sign-in page. Two things carry over the trip:
 *
 *   1. window.rtrMarkSignInReturn() (shared_static/clerk_nav.js) stashes
 *      this page's URL, so sign-up returns the visitor here, not to
 *      /account/saved.
 *   2. PENDING_KEY remembers which button they clicked. When they come
 *      back signed in to the same URL, resumePendingSave() clicks that
 *      button for them, so the meeting or search they meant to save is
 *      actually saved. It expires after 30 minutes and fires at most once.
 *
 * GA events (low-cardinality params only, same rule as WO-9):
 *   signup_prompt_shown     {feature}
 *   signup_prompt_click     {feature, action: sign_up | sign_in | dismiss}
 *   signup_prompt_completed {feature}   -- the pending save went through
 *
 * Every storage access is wrapped: with storage blocked the box still
 * works, the visitor just has to click Save again after signing in.
 */
(function () {
  const PENDING_KEY = 'rtrPendingSave';
  const PENDING_MAX_AGE_MS = 30 * 60 * 1000;

  const COPY = {
    save_meeting: {
      title: 'Save this meeting',
      lead: 'Saving meetings needs a free account. It takes about a minute.',
    },
    save_search: {
      title: 'Save this search',
      lead: 'Saving searches needs a free account. It takes about a minute.',
    },
  };

  const PERKS = [
    'Save meetings and come back to them any time.',
    'Save a search and get an email when a new meeting matches it.',
    'Hear first about new tools for following your local government.',
  ];

  function track(name, params) {
    if (typeof window.trackEvent === 'function') window.trackEvent(name, params);
  }

  function isSignedOut(btn) {
    // Only an explicit "false" means signed out: markup without the
    // attribute keeps the old behavior (call the API directly).
    if (!btn || btn.dataset.signedIn !== 'false') return false;
    if (window.RTRClerk && window.RTRClerk.isSignedIn && window.RTRClerk.isSignedIn()) {
      return false;
    }
    return true;
  }

  let dialogEl = null;
  let currentFeature = null;
  let currentButtonId = null;

  function stashPending() {
    try {
      sessionStorage.setItem(
        PENDING_KEY,
        JSON.stringify({
          buttonId: currentButtonId,
          feature: currentFeature,
          url: window.location.href,
          at: Date.now(),
        })
      );
    } catch (e) {
      // Storage blocked -- sign-up still works, no auto-save afterwards.
    }
  }

  function go(action, href) {
    track('signup_prompt_click', { feature: currentFeature, action: action });
    stashPending();
    if (typeof window.rtrMarkSignInReturn === 'function') window.rtrMarkSignInReturn();
    window.location.href = href;
  }

  function close(reason) {
    if (!dialogEl || !dialogEl.open) return;
    if (reason === 'dismiss') {
      track('signup_prompt_click', { feature: currentFeature, action: 'dismiss' });
    }
    if (typeof dialogEl.close === 'function') dialogEl.close();
    else dialogEl.removeAttribute('open');
  }

  function build() {
    const d = document.createElement('dialog');
    d.className = 'signup-prompt';
    d.setAttribute('aria-labelledby', 'signupPromptTitle');

    const h = document.createElement('h2');
    h.id = 'signupPromptTitle';
    h.className = 'signup-prompt-title';
    d.appendChild(h);

    const lead = document.createElement('p');
    lead.className = 'signup-prompt-lead';
    d.appendChild(lead);

    const ul = document.createElement('ul');
    ul.className = 'signup-prompt-perks';
    PERKS.forEach((text) => {
      const li = document.createElement('li');
      li.textContent = text;
      ul.appendChild(li);
    });
    d.appendChild(ul);

    const actions = document.createElement('div');
    actions.className = 'signup-prompt-actions';

    const signUp = document.createElement('a');
    signUp.href = '/sign-up';
    signUp.className = 'cassette-btn signup-prompt-primary';
    signUp.innerHTML = '<span class="cassette-label">Create a free account</span>';
    signUp.addEventListener('click', (e) => {
      e.preventDefault();
      go('sign_up', '/sign-up');
    });

    const signIn = document.createElement('a');
    signIn.href = '/sign-in';
    signIn.className = 'signup-prompt-signin';
    signIn.textContent = 'I already have an account';
    signIn.addEventListener('click', (e) => {
      e.preventDefault();
      go('sign_in', '/sign-in');
    });

    const notNow = document.createElement('button');
    notNow.type = 'button';
    notNow.className = 'link-button signup-prompt-dismiss';
    notNow.textContent = 'Not now';
    notNow.addEventListener('click', () => close('dismiss'));

    actions.append(signUp, signIn, notNow);
    d.appendChild(actions);

    const fine = document.createElement('p');
    fine.className = 'signup-prompt-fine';
    fine.textContent = 'Free. Everything else on the site stays open without an account.';
    d.appendChild(fine);

    // Esc closes a modal <dialog> natively; count it as a dismiss too.
    d.addEventListener('cancel', (e) => {
      e.preventDefault();
      close('dismiss');
    });
    // A click on the backdrop lands on the <dialog> element itself.
    d.addEventListener('click', (e) => {
      if (e.target === d) close('dismiss');
    });

    document.body.appendChild(d);
    return d;
  }

  function open(opts) {
    currentFeature = (opts && opts.feature) || 'save_meeting';
    currentButtonId = (opts && opts.buttonId) || null;
    if (!dialogEl) dialogEl = build();
    const copy = COPY[currentFeature] || COPY.save_meeting;
    dialogEl.querySelector('.signup-prompt-title').textContent = copy.title;
    dialogEl.querySelector('.signup-prompt-lead').textContent = copy.lead;
    if (!dialogEl.open) {
      if (typeof dialogEl.showModal === 'function') dialogEl.showModal();
      else dialogEl.setAttribute('open', '');
    }
    track('signup_prompt_shown', { feature: currentFeature });
  }

  function readPending() {
    try {
      const raw = sessionStorage.getItem(PENDING_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) {
      return null;
    }
  }

  function clearPending() {
    try {
      sessionStorage.removeItem(PENDING_KEY);
    } catch (e) {
      // Nothing to do.
    }
  }

  function resumePendingSave() {
    const pending = readPending();
    if (!pending) return;
    const signedIn = !!(window.RTRClerk && window.RTRClerk.isSignedIn && window.RTRClerk.isSignedIn());
    if (!signedIn) {
      // Still signed out (they backed out of sign-up). Keep it until it
      // expires, in case they finish sign-up in this tab.
      if (Date.now() - (pending.at || 0) > PENDING_MAX_AGE_MS) clearPending();
      return;
    }
    clearPending();
    if (Date.now() - (pending.at || 0) > PENDING_MAX_AGE_MS) return;
    if (pending.url !== window.location.href) return;
    const btn = pending.buttonId ? document.getElementById(pending.buttonId) : null;
    if (!btn || btn.disabled || btn.dataset.saved === 'true') return;
    // The server rendered this page before it knew about the session in
    // some cases; the button's own handler re-checks isSignedOut(), which
    // now sees RTRClerk signed in and calls the save API.
    btn.dataset.signedIn = 'true';
    btn.click();
    track('signup_prompt_completed', { feature: pending.feature || 'save_meeting' });
  }

  document.addEventListener('rtr-clerk-ready', resumePendingSave);

  window.RTRSignupPrompt = {
    isSignedOut: isSignedOut,
    open: open,
    close: close,
    resumePendingSave: resumePendingSave,
  };
})();
