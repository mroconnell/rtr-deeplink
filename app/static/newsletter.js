document.addEventListener('DOMContentLoaded', () => {
  const form = document.getElementById('newsletterForm');
  if (!form) return;

  const emailInput = document.getElementById('newsletterEmail');
  const message = document.getElementById('newsletterMessage');
  const button = form.querySelector('button[type="submit"]');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = emailInput.value.trim();
    if (!email) return;

    button.disabled = true;
    message.hidden = true;

    let data;
    try {
      const res = await fetch('/api/newsletter/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      data = await res.json();
    } catch (err) {
      data = { error: 'network_error' };
    }

    if (data.status === 'subscribed' || data.status === 'already_subscribed') {
      message.textContent = data.status === 'already_subscribed'
        ? "You're already on the list!"
        : "Thanks — you're on the list!";
      message.className = 'newsletter-message newsletter-message-success';
      emailInput.value = '';
    } else {
      message.textContent = data.message || 'Something went wrong — please try again.';
      message.className = 'newsletter-message newsletter-message-error';
    }

    message.hidden = false;
    button.disabled = false;
  });
});
