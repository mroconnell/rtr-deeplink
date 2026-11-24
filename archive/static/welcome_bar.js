/* Welcome bar for visitors who arrive on a shared moment (2026-11-24).
 *
 * Why: about 450 visits a month land on a meeting page through a link with
 * a time in it (t=). They engage at 47% against 17% for other visits, and
 * about half come from ChatGPT. Until now nothing asked them anything.
 *
 * When it shows (all must hold):
 *   - the URL has t= (a shared moment),
 *   - the visitor came from another site or typed the link (referrer is
 *     not this site), so it greets arrivals, not people clicking around,
 *   - Clerk loaded and the visitor is signed out,
 *   - this browser has not dismissed or finished it before.
 *
 * What it does: email -> Clerk emails a 6-digit code -> the code creates
 * a free account (or signs in an existing one) -> we save a search for
 * this meeting's jurisdiction -> the existing saved-search alert email
 * (archive/search_alerts.py) tells them about new meetings. No password:
 * Clerk production has "Sign-up with password" off since 2026-11-24.
 * Anything this flow cannot finish in place (a second factor, a device
 * check) falls back to the normal /sign-in or /sign-up page.
 *
 * GA: one event, welcome_bar, with a low-cardinality `step`:
 *   shown, email_submitted, code_sent, verified, saved, dismissed, error
 * plus `path` (sign_up | sign_in) on verified, and `stage` on error.
 */
(function () {
  const DONE_KEY = 'rtrWelcomeBarDone';

  function track(step, extra) {
    if (typeof window.trackEvent === 'function') {
      window.trackEvent('welcome_bar', Object.assign({ step: step }, extra || {}));
    }
  }

  function formatTime(seconds) {
    const s = Math.max(0, Math.floor(seconds));
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    const pad = (n) => String(n).padStart(2, '0');
    return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  }

  function sharedMomentSeconds() {
    const raw = new URLSearchParams(window.location.search).get('t');
    if (raw === null || raw === '') return null;
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? n : null;
  }

  function cameFromElsewhere() {
    if (!document.referrer) return true;
    try {
      return new URL(document.referrer).host !== window.location.host;
    } catch (e) {
      return true;
    }
  }

  function alreadyDone() {
    try {
      return !!localStorage.getItem(DONE_KEY);
    } catch (e) {
      return false;
    }
  }

  function markDone(how) {
    try {
      localStorage.setItem(DONE_KEY, how);
    } catch (e) {
      // Storage blocked: the bar may show again next visit. Harmless.
    }
  }

  function clerkErrorCode(err) {
    return (err && err.errors && err.errors[0] && err.errors[0].code) || '';
  }

  function clerkErrorMessage(err) {
    const first = err && err.errors && err.errors[0];
    return (first && (first.longMessage || first.message)) || '';
  }

  function shouldShow(bar) {
    if (!bar) return false;
    if (sharedMomentSeconds() === null) return false;
    if (!cameFromElsewhere()) return false;
    if (alreadyDone()) return false;
    if (!window.Clerk || !window.Clerk.client) return false;
    if (window.RTRClerk && window.RTRClerk.isSignedIn && window.RTRClerk.isSignedIn()) return false;
    return true;
  }

  function wire(bar) {
    const emailForm = bar.querySelector('#welcomeBarEmailForm');
    const codeForm = bar.querySelector('#welcomeBarCodeForm');
    const emailInput = bar.querySelector('#welcomeBarEmail');
    const codeInput = bar.querySelector('#welcomeBarCode');
    const statusEl = bar.querySelector('#welcomeBarStatus');
    const jurisdiction = bar.dataset.jurisdiction;
    const display = bar.dataset.jurisdictionDisplay || jurisdiction;

    // The in-progress attempt: { path: 'sign_up'|'sign_in', resource }.
    let attempt = null;

    const setStatus = (text, isError) => {
      statusEl.textContent = text || '';
      statusEl.classList.toggle('error', !!isError);
    };
    const setBusy = (form, busy) => {
      form.querySelectorAll('button, input').forEach((el) => { el.disabled = busy; });
    };
    const fallback = (stage, page) => {
      track('error', { stage: stage });
      if (typeof window.rtrMarkSignInReturn === 'function') window.rtrMarkSignInReturn();
      setStatus('');
      const link = document.createElement('a');
      link.href = page;
      link.textContent = page === '/sign-up' ? 'finish on the sign-up page' : 'finish on the sign-in page';
      statusEl.append('Almost there: please ', link, '.');
    };

    async function startSignIn(email) {
      const signIn = await window.Clerk.client.signIn.create({ identifier: email });
      const factor = (signIn.supportedFirstFactors || []).find((f) => f.strategy === 'email_code');
      if (!factor) return null;
      await signIn.prepareFirstFactor({ strategy: 'email_code', emailAddressId: factor.emailAddressId });
      return { path: 'sign_in', resource: signIn };
    }

    async function startSignUp(email) {
      const signUp = await window.Clerk.client.signUp.create({ emailAddress: email });
      await signUp.prepareEmailAddressVerification({ strategy: 'email_code' });
      return { path: 'sign_up', resource: signUp };
    }

    async function saveAlert() {
      const res = await fetch('/api/account/save-search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ search_params: { jurisdiction: jurisdiction } }),
      });
      return res.ok;
    }

    emailForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = emailInput.value.trim();
      if (!email || !emailInput.checkValidity()) {
        setStatus('Please enter a valid email address.', true);
        return;
      }
      track('email_submitted');
      setBusy(emailForm, true);
      setStatus('Sending your code…');
      try {
        try {
          attempt = await startSignUp(email);
        } catch (err) {
          // Already has an account: send a sign-in code instead.
          if (clerkErrorCode(err) === 'form_identifier_exists') {
            attempt = await startSignIn(email);
          } else {
            throw err;
          }
        }
        if (!attempt) {
          fallback('no_email_code', '/sign-in');
          return;
        }
        track('code_sent', { path: attempt.path });
        emailForm.hidden = true;
        codeForm.hidden = false;
        setStatus(`We sent a code to ${email}. It can take a minute to arrive.`);
        codeInput.focus();
      } catch (err) {
        track('error', { stage: 'send_code' });
        setStatus(clerkErrorMessage(err) || 'Something went wrong. Please try again.', true);
      } finally {
        setBusy(emailForm, false);
      }
    });

    codeForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const code = codeInput.value.replace(/\D/g, '');
      if (code.length !== 6 || !attempt) {
        setStatus('Please enter the 6-digit code from the email.', true);
        return;
      }
      setBusy(codeForm, true);
      setStatus('Checking…');
      try {
        const result = attempt.path === 'sign_up'
          ? await attempt.resource.attemptEmailAddressVerification({ code: code })
          : await attempt.resource.attemptFirstFactor({ strategy: 'email_code', code: code });
        if (result.status !== 'complete' || !result.createdSessionId) {
          // A second factor, device check or missing field: let Clerk's
          // own page finish it.
          fallback('not_complete', attempt.path === 'sign_up' ? '/sign-up' : '/sign-in');
          return;
        }
        await window.Clerk.setActive({ session: result.createdSessionId });
        track('verified', { path: attempt.path });
        markDone('verified');
        if (await saveAlert()) {
          track('saved');
          codeForm.hidden = true;
          setStatus(`You're all set. We'll email you when ${display} posts a new meeting.`);
        } else {
          track('error', { stage: 'save' });
          codeForm.hidden = true;
          setStatus('You are signed in, but the alert did not save. Use "Save this search" on the meetings page to try again.', true);
        }
      } catch (err) {
        track('error', { stage: 'verify' });
        setStatus(clerkErrorMessage(err) || 'That code did not work. Please check it and try again.', true);
      } finally {
        setBusy(codeForm, false);
      }
    });

    bar.querySelectorAll('.welcome-bar-dismiss').forEach((btn) => {
      btn.addEventListener('click', () => {
        track('dismissed');
        markDone('dismissed');
        bar.hidden = true;
      });
    });
  }

  function init() {
    const bar = document.getElementById('welcomeBar');
    if (!shouldShow(bar)) return;
    const timeEl = bar.querySelector('.welcome-bar-time');
    if (timeEl) timeEl.textContent = formatTime(sharedMomentSeconds());
    wire(bar);
    bar.hidden = false;
    // The bar is fixed to the bottom of the window: pad the page by its
    // height so it never covers the end of the page (footer, last lines).
    const pad = () => {
      document.body.style.paddingBottom = bar.hidden ? '' : bar.offsetHeight + 'px';
    };
    pad();
    window.addEventListener('resize', pad);
    bar.querySelectorAll('.welcome-bar-dismiss').forEach((btn) => btn.addEventListener('click', pad));
    track('shown');
  }

  document.addEventListener('rtr-clerk-ready', init);

  window.RTRWelcomeBar = { formatTime: formatTime, shouldShow: shouldShow, init: init };
})();
