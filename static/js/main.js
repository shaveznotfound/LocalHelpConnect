/**
 * Local Help Connect — Main JavaScript
 * Handles: nav scroll, mobile menu, flash auto-dismiss, animations
 */

document.addEventListener('DOMContentLoaded', () => {

  // ─── NAVBAR SCROLL EFFECT ──────────────────────────────────
  const nav = document.getElementById('mainNav');
  if (nav) {
    window.addEventListener('scroll', () => {
      nav.classList.toggle('scrolled', window.scrollY > 20);
    });
  }

  // ─── MOBILE MENU TOGGLE ────────────────────────────────────
  const navToggle = document.getElementById('navToggle');
  const mobileMenu = document.getElementById('mobileMenu');
  if (navToggle && mobileMenu) {
    navToggle.addEventListener('click', () => {
      mobileMenu.classList.toggle('open');
      const icon = navToggle.querySelector('i');
      icon.className = mobileMenu.classList.contains('open') ? 'ph ph-x' : 'ph ph-list';
    });
    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!nav.contains(e.target)) {
        mobileMenu.classList.remove('open');
        const icon = navToggle.querySelector('i');
        if (icon) icon.className = 'ph ph-list';
      }
    });
  }

  // ─── FLASH AUTO-DISMISS ───────────────────────────────────
  const flashes = document.querySelectorAll('.flash-alert');
  flashes.forEach((el, i) => {
    setTimeout(() => {
      el.style.transition = 'opacity 0.5s, transform 0.5s';
      el.style.opacity = '0';
      el.style.transform = 'translateX(20px)';
      setTimeout(() => el.remove(), 500);
    }, 4000 + i * 500);
  });

  // ─── CONFIRM BEFORE REJECT ────────────────────────────────
  document.querySelectorAll('.btn-reject').forEach(btn => {
    btn.addEventListener('click', (e) => {
      if (!confirm('Are you sure you want to decline this request?')) {
        e.preventDefault();
      }
    });
  });

  // ─── ANIMATE STAT NUMBERS ─────────────────────────────────
  const statNums = document.querySelectorAll('.stat-card-num');
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const el = entry.target;
        const target = parseInt(el.textContent);
        if (!isNaN(target) && target > 0) {
          animateCount(el, target);
        }
        observer.unobserve(el);
      }
    });
  }, { threshold: 0.5 });

  statNums.forEach(el => observer.observe(el));

  function animateCount(el, target) {
    const duration = 600;
    const step = target / (duration / 16);
    let current = 0;
    const saved = el.textContent; // preserve text if not pure number
    if (isNaN(parseInt(saved))) return;
    const timer = setInterval(() => {
      current += step;
      if (current >= target) {
        el.textContent = target;
        clearInterval(timer);
      } else {
        el.textContent = Math.floor(current);
      }
    }, 16);
  }

  // ─── STAGGERED CARD ANIMATIONS ────────────────────────────
  const cards = document.querySelectorAll('.worker-card, .request-full-card, .request-card, .how-card, .why-card, .cat-card');
  const cardObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry, i) => {
      if (entry.isIntersecting) {
        setTimeout(() => {
          entry.target.style.opacity = '1';
          entry.target.style.transform = 'translateY(0)';
        }, i * 60);
        cardObserver.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });

  cards.forEach((card, i) => {
    card.style.opacity = '0';
    card.style.transform = 'translateY(16px)';
    card.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    cardObserver.observe(card);
  });

  // ─── FORM INPUT ENHANCEMENT ───────────────────────────────
  // Add floating label effect on focus
  document.querySelectorAll('.form-input, .form-textarea').forEach(input => {
    const group = input.closest('.form-group');
    if (!group) return;
    input.addEventListener('focus', () => group.classList.add('focused'));
    input.addEventListener('blur', () => group.classList.remove('focused'));
  });

  // ─── AVAILABILITY BADGE COLOR ─────────────────────────────
  document.querySelectorAll('[class*="avail-"]').forEach(el => {
    const cls = [...el.classList].find(c => c.startsWith('avail-') && !c.includes('dot') && !c.includes('option') && !c.includes('select'));
    if (!cls) return;
    const avail = cls.replace('avail-', '');
    const colorMap = { available: '#22c55e', busy: '#f59e0b', offline: '#94a3b8' };
    if (colorMap[avail] && el.querySelector('i.ph-fill.ph-circle')) {
      el.querySelector('i.ph-fill.ph-circle').style.color = colorMap[avail];
    }
  });

});
