(function() {
  const loginForm = document.getElementById('loginForm');
  const registerForm = document.getElementById('registerForm');
  const forgotForm = document.getElementById('forgotForm');
  const resetForm = document.getElementById('resetForm');
  
  function showForm(name) {
    loginForm.style.display = name === 'login' ? 'block' : 'none';
    registerForm.style.display = name === 'register' ? 'block' : 'none';
    forgotForm.style.display = name === 'forgot' ? 'block' : 'none';
    resetForm.style.display = name === 'reset' ? 'block' : 'none';
  }
  
  function showError(el, msg) {
    el.textContent = msg;
    el.classList.add('show');
  }
  
  function hideError(el) {
    el.classList.remove('show');
    el.textContent = '';
  }
  
  document.getElementById('showRegister')?.addEventListener('click', (e) => {
    e.preventDefault();
    showForm('register');
  });
  
  document.getElementById('showLogin')?.addEventListener('click', (e) => {
    e.preventDefault();
    showForm('login');
  });
  
  document.getElementById('showForgot')?.addEventListener('click', (e) => {
    e.preventDefault();
    showForm('forgot');
  });
  
  document.getElementById('backToLogin')?.addEventListener('click', (e) => {
    e.preventDefault();
    showForm('login');
  });
  
  document.getElementById('backToLogin2')?.addEventListener('click', (e) => {
    e.preventDefault();
    showForm('login');
  });
  
  loginForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('loginError');
    hideError(errEl);
    
    const identifier = document.getElementById('loginIdentifier').value.trim();
    const password = document.getElementById('loginPassword').value;
    const remember = document.getElementById('loginRemember').checked;
    
    try {
      const res = await API.post('/api/auth/login', { identifier, password, remember });
      window.location.href = '/chat';
    } catch (err) {
      showError(errEl, err.data?.error || err.message || 'Login failed');
    }
  });
  
  registerForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('registerError');
    hideError(errEl);
    
    const data = {
      display_name: document.getElementById('regDisplayName').value.trim(),
      username: document.getElementById('regUsername').value.trim(),
      email: document.getElementById('regEmail').value.trim(),
      password: document.getElementById('regPassword').value
    };
    
    try {
      await API.post('/api/auth/register', data);
      window.location.href = '/chat';
    } catch (err) {
      let msg = err.data?.error || err.message || 'Registration failed';
      if (err.data?.errors) {
        msg = Object.values(err.data.errors).join('. ');
      }
      showError(errEl, msg);
    }
  });
  
  forgotForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('forgotError');
    hideError(errEl);
    
    const email = document.getElementById('forgotEmail').value.trim();
    
    try {
      const res = await API.post('/api/auth/forgot-password', { email });
      if (res.dev_token) {
        // Development mode - show token
        showForm('reset');
        document.getElementById('resetToken').value = res.dev_token;
        errEl.style.color = 'var(--success)';
        showError(errEl, 'Dev mode: token pre-filled. Set your new password.');
      } else {
        errEl.style.color = 'var(--success)';
        showError(errEl, res.message || 'If an account exists, a reset link has been sent.');
      }
    } catch (err) {
      showError(errEl, err.data?.error || 'Request failed');
    }
  });
  
  resetForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const errEl = document.getElementById('resetError');
    hideError(errEl);
    
    const token = document.getElementById('resetToken').value.trim();
    const password = document.getElementById('resetPassword').value;
    
    try {
      await API.post('/api/auth/reset-password', { token, password });
      errEl.style.color = 'var(--success)';
      showError(errEl, 'Password reset successful. You can now sign in.');
      setTimeout(() => showForm('login'), 2000);
    } catch (err) {
      showError(errEl, err.data?.error || 'Reset failed');
    }
  });
  
  // Check URL for reset token
  const params = new URLSearchParams(window.location.search);
  if (params.get('token')) {
    showForm('reset');
    document.getElementById('resetToken').value = params.get('token');
  }
})();
