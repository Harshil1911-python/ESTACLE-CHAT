const API = {
  async request(method, path, data = null, isForm = false) {
    const opts = {
      method,
      credentials: 'same-origin',
      headers: {}
    };
    
    if (data && !isForm) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(data);
    } else if (data && isForm) {
      opts.body = data; // FormData
    }
    
    const res = await fetch(path, opts);
    
    if (res.status === 401) {
      if (!window.location.pathname.startsWith('/login') && window.location.pathname !== '/') {
        window.location.href = '/';
      }
      throw new Error('Unauthorized');
    }
    
    const json = await res.json().catch(() => ({}));
    
    if (!res.ok) {
      const err = new Error(json.error || 'Request failed');
      err.status = res.status;
      err.data = json;
      throw err;
    }
    
    return json;
  },
  
  get(path) { return this.request('GET', path); },
  post(path, data) { return this.request('POST', path, data); },
  put(path, data) { return this.request('PUT', path, data); },
  delete(path, data) { return this.request('DELETE', path, data); },
  
  async upload(path, formData) {
    return this.request('POST', path, formData, true);
  }
};
