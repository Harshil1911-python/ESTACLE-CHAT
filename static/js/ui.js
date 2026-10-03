const UI = {
  toast(message, type = 'info', duration = 3000) {
    const container = document.getElementById('toastContainer');
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.opacity = '0';
      el.style.transition = 'opacity 0.3s';
      setTimeout(() => el.remove(), 300);
    }, duration);
  },
  
  showModal(title, bodyHtml, footerHtml = '') {
    document.getElementById('modalTitle').textContent = title;
    document.getElementById('modalBody').innerHTML = bodyHtml;
    document.getElementById('modalFooter').innerHTML = footerHtml;
    document.getElementById('modalOverlay').classList.add('open');
  },
  
  hideModal() {
    document.getElementById('modalOverlay').classList.remove('open');
  },
  
  confirm(title, message) {
    return new Promise((resolve) => {
      this.showModal(title, `<p style="font-size:14px;color:var(--text-secondary);">${message}</p>`,
        `<button class="btn btn-secondary" id="confirmCancel">Cancel</button>
         <button class="btn btn-danger" id="confirmOk">Confirm</button>`
      );
      document.getElementById('confirmCancel').onclick = () => { this.hideModal(); resolve(false); };
      document.getElementById('confirmOk').onclick = () => { this.hideModal(); resolve(true); };
    });
  },
  
  getInitials(name) {
    if (!name) return '?';
    return name.split(' ').map(w => w[0]).slice(0, 2).join('').toUpperCase();
  },
  
  formatTime(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    const diff = now - d;
    
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return Math.floor(diff / 60000) + 'm';
    if (d.toDateString() === now.toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    if (diff < 604800000) {
      return d.toLocaleDateString([], { weekday: 'short' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
  },
  
  formatDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Today';
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  },
  
  formatFileSize(bytes) {
    if (!bytes) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  },
  
  formatDuration(seconds) {
    if (!seconds) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return m + ':' + String(s).padStart(2, '0');
  },
  
  avatarHtml(user, size = 48) {
    if (!user) return `<div class="avatar">?</div>`;
    if (user.profile_photo || user.photo) {
      const src = user.profile_photo ? `/uploads/${user.profile_photo}` : `/uploads/${user.photo}`;
      return `<div class="avatar"><img src="${src}" alt=""></div>`;
    }
    return `<div class="avatar">${this.getInitials(user.display_name || user.name || '?')}</div>`;
  },
  
  escapeHtml(text) {
    const d = document.createElement('div');
    d.textContent = text || '';
    return d.innerHTML;
  },
  
  linkify(text) {
    if (!text) return '';
    const escaped = this.escapeHtml(text);
    return escaped.replace(
      /(https?:\/\/[^\s<]+)/g,
      '<a href="$1" target="_blank" rel="noopener">$1</a>'
    );
  },
  
  isMobile() {
    return window.innerWidth <= 768;
  },
  
  applyTheme(theme) {
    if (theme === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else if (theme === 'light') {
      document.documentElement.setAttribute('data-theme', 'light');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    localStorage.setItem('estacle-theme', theme);
  }
};

// Modal close handlers
document.getElementById('modalClose')?.addEventListener('click', () => UI.hideModal());
document.getElementById('modalOverlay')?.addEventListener('click', (e) => {
  if (e.target === document.getElementById('modalOverlay')) UI.hideModal();
});
