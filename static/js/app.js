const AppState = {
  user: null,
  conversations: [],
  currentConvId: null,
  messages: {},
  typingUsers: {},
  replyTo: null,
  mediaRecorder: null,
  recordingChunks: [],
  recordingStart: null,
  offlineQueue: JSON.parse(localStorage.getItem('estacle-offline-queue') || '[]'),
};

// ========== INIT ==========
async function initApp() {
  try {
    const res = await API.get('/api/auth/me');
    AppState.user = res.user;
    
    // Theme
    UI.applyTheme(AppState.user.theme || 'system');
    
    // Socket
    SocketManager.connect();
    setupSocketHandlers();
    
    // WebRTC
    await WebRTCManager.init();
    
    // Load conversations
    await loadConversations();
    
    // Setup UI events
    setupEventListeners();
    
    // Online/offline
    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    if (!navigator.onLine) handleOffline();
    
    // Check URL params
    const params = new URLSearchParams(window.location.search);
    if (params.get('c')) {
      openConversation(parseInt(params.get('c')));
    }
  } catch (e) {
    console.error('Init failed:', e);
    window.location.href = '/';
  }
}

// ========== CONVERSATIONS ==========
async function loadConversations() {
  try {
    const res = await API.get('/api/chats/');
    AppState.conversations = res.conversations || [];
    renderChatList();
  } catch (e) {
    UI.toast('Failed to load conversations', 'error');
  }
}

function renderChatList() {
  const list = document.getElementById('chatList');
  const empty = document.getElementById('chatListEmpty');
  
  if (!AppState.conversations.length) {
    list.innerHTML = '';
    list.appendChild(empty);
    empty.style.display = 'flex';
    return;
  }
  
  empty.style.display = 'none';
  
  list.innerHTML = AppState.conversations.map(conv => {
    const name = conv.name || conv.other_user?.display_name || 'Chat';
    const photo = conv.photo || conv.other_user?.profile_photo;
    const preview = conv.last_message?.content || (conv.last_message?.message_type !== 'text' ? conv.last_message?.message_type : '') || '';
    const time = UI.formatTime(conv.last_message?.created_at || conv.updated_at);
    const active = conv.id === AppState.currentConvId ? 'active' : '';
    const pinned = conv.is_pinned ? 'pinned' : '';
    const online = conv.is_online || conv.other_user?.is_online;
    
    return `
      <div class="chat-item ${active} ${pinned}" data-id="${conv.id}" onclick="openConversation(${conv.id})">
        <div class="avatar">
          ${photo ? `<img src="/uploads/${photo}" alt="">` : UI.getInitials(name)}
          ${online ? '<span class="online-dot"></span>' : ''}
        </div>
        <div class="chat-item-content">
          <div class="chat-item-top">
            <span class="chat-item-name">${UI.escapeHtml(name)}</span>
            <span class="chat-item-time">${time}</span>
          </div>
          <div class="chat-item-bottom">
            <span class="chat-item-preview">${UI.escapeHtml(preview)}</span>
            ${conv.unread_count ? `<span class="chat-item-badge">${conv.unread_count}</span>` : ''}
          </div>
        </div>
      </div>
    `;
  }).join('');
}

async function openConversation(convId) {
  AppState.currentConvId = convId;
  AppState.replyTo = null;
  document.getElementById('replyPreview').classList.remove('show');
  
  // UI updates
  document.getElementById('welcomeScreen').style.display = 'none';
  const active = document.getElementById('activeConversation');
  active.style.display = 'flex';
  
  if (UI.isMobile()) {
    document.getElementById('sidebar').classList.add('hidden-mobile');
    document.getElementById('conversationPanel').classList.remove('hidden-mobile');
  }
  
  renderChatList();
  
  // Load conversation details
  try {
    const res = await API.get(`/api/chats/${convId}`);
    const conv = res.conversation;
    
    const name = conv.name || conv.other_user?.display_name || 'Chat';
    const photo = conv.photo || conv.other_user?.profile_photo;
    
    document.getElementById('convName').textContent = name;
    document.getElementById('convAvatar').innerHTML = photo
      ? `<img src="/uploads/${photo}" alt="">`
      : UI.getInitials(name);
    
    const status = document.getElementById('convStatus');
    if (conv.type === 'private' && conv.other_user) {
      if (conv.other_user.is_online) {
        status.textContent = 'Online';
        status.classList.add('online');
      } else {
        status.textContent = conv.other_user.last_seen
          ? 'Last seen ' + UI.formatTime(conv.other_user.last_seen)
          : '';
        status.classList.remove('online');
      }
    } else {
      status.textContent = (conv.member_count || conv.members?.length || 0) + ' members';
      status.classList.remove('online');
    }
    
    // Join socket room
    SocketManager.joinConversation(convId);
    
    // Load messages
    await loadMessages(convId);
    
    // Mark as read
    API.post(`/api/chats/${convId}/read`, {});
  } catch (e) {
    UI.toast('Failed to open conversation', 'error');
  }
}

// ========== MESSAGES ==========
async function loadMessages(convId, beforeId = null) {
  try {
    let url = `/api/messages/${convId}?limit=40`;
    if (beforeId) url += `&before_id=${beforeId}`;
    
    const res = await API.get(url);
    const msgs = res.messages || [];
    
    if (!AppState.messages[convId]) AppState.messages[convId] = [];
    
    if (beforeId) {
      AppState.messages[convId] = [...msgs, ...AppState.messages[convId]];
    } else {
      AppState.messages[convId] = msgs;
    }
    
    renderMessages(convId);
    
    if (!beforeId) {
      scrollToBottom();
    }
    
    // Mark delivered/read
    const unreadIds = msgs.filter(m => m.sender_id !== AppState.user.id).map(m => m.id);
    if (unreadIds.length) {
      SocketManager.messagesRead(convId, unreadIds);
    }
  } catch (e) {
    console.error('Load messages failed:', e);
  }
}

function renderMessages(convId) {
  const area = document.getElementById('messagesArea');
  const msgs = AppState.messages[convId] || [];
  
  let html = '';
  let lastDate = '';
  
  msgs.forEach(msg => {
    if (!msg) return;
    
    const date = UI.formatDate(msg.created_at);
    if (date !== lastDate) {
      html += `<div class="date-separator"><span>${date}</span></div>`;
      lastDate = date;
    }
    
    html += renderMessage(msg);
  });
  
  area.innerHTML = html;
}

function renderMessage(msg) {
  if (msg.message_type === 'system') {
    return `<div class="message system"><div class="message-bubble">${UI.escapeHtml(msg.content)}</div></div>`;
  }
  
  const isOut = msg.sender_id === AppState.user.id;
  const cls = isOut ? 'outgoing' : 'incoming';
  
  let content = '';
  
  // Attachments
  if (msg.attachments && msg.attachments.length) {
    msg.attachments.forEach(att => {
      if (att.file_type === 'image') {
        content += `<div class="message-attachment"><img src="${att.url}" alt="" onclick="window.open('${att.url}')"></div>`;
      } else if (att.file_type === 'video') {
        content += `<div class="message-attachment"><video src="${att.url}" controls></video></div>`;
      } else if (att.file_type === 'audio') {
        content += renderVoiceMessage(att);
      } else {
        content += `<div class="message-file" onclick="window.open('${att.url}')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/></svg>
          <div class="message-file-info">
            <div class="message-file-name">${UI.escapeHtml(att.original_filename)}</div>
            <div class="message-file-size">${UI.formatFileSize(att.file_size)}</div>
          </div>
        </div>`;
      }
    });
  }
  
  if (msg.content) {
    content += `<div class="message-content">${UI.linkify(msg.content)}</div>`;
  }
  
  if (msg.is_deleted_for_everyone) {
    content = `<div class="message-content" style="font-style:italic;opacity:0.7;">This message was deleted</div>`;
  }
  
  // Status icons for outgoing
  let statusHtml = '';
  if (isOut) {
    if (msg.status === 'read') {
      statusHtml = '<span class="message-status"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L7 17l-5-5"/><path d="M22 6L11 17"/></svg></span>';
    } else if (msg.status === 'delivered') {
      statusHtml = '<span class="message-status"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L7 17l-5-5"/><path d="M22 6L11 17"/></svg></span>';
    } else {
      statusHtml = '<span class="message-status"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 6L9 17l-5-5"/></svg></span>';
    }
  }
  
  const senderName = !isOut && msg.sender ? `<div class="message-sender">${UI.escapeHtml(msg.sender.display_name)}</div>` : '';
  
  return `
    <div class="message ${cls}" data-id="${msg.id}" oncontextmenu="showMessageMenu(event, ${msg.id})">
      <div class="message-bubble">
        ${senderName}
        ${content}
        <div class="message-meta">
          ${msg.is_edited ? '<span>edited</span>' : ''}
          <span>${UI.formatTime(msg.created_at)}</span>
          ${statusHtml}
        </div>
      </div>
    </div>
  `;
}

function renderVoiceMessage(att) {
  const duration = UI.formatDuration(att.duration || 0);
  const bars = Array.from({length: 20}, () => {
    const h = 4 + Math.random() * 20;
    return `<div class="bar" style="height:${h}px;"></div>`;
  }).join('');
  
  return `
    <div class="voice-message">
      <button class="voice-play-btn" onclick="playVoice(this, '${att.url}')">
        <svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
      </button>
      <div class="voice-waveform">${bars}</div>
      <span class="voice-duration">${duration}</span>
    </div>
  `;
}

function playVoice(btn, url) {
  const audio = new Audio(url);
  audio.play();
  btn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>';
  audio.onended = () => {
    btn.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>';
  };
}

function scrollToBottom() {
  const area = document.getElementById('messagesArea');
  area.scrollTop = area.scrollHeight;
}

// ========== SEND MESSAGE ==========
async function sendMessage() {
  const input = document.getElementById('messageInput');
  const content = input.value.trim();
  if (!content || !AppState.currentConvId) return;
  
  input.value = '';
  autoResize(input);
  document.getElementById('btnSend').disabled = true;
  
  const data = {
    content,
    message_type: 'text',
  };
  
  if (AppState.replyTo) {
    data.reply_to_id = AppState.replyTo;
    AppState.replyTo = null;
    document.getElementById('replyPreview').classList.remove('show');
  }
  
  SocketManager.typingStop(AppState.currentConvId);
  
  if (!navigator.onLine) {
    // Queue offline
    AppState.offlineQueue.push({ convId: AppState.currentConvId, data });
    localStorage.setItem('estacle-offline-queue', JSON.stringify(AppState.offlineQueue));
    UI.toast('Message queued for sending', 'info');
    return;
  }
  
  try {
    const res = await API.post(`/api/messages/${AppState.currentConvId}`, data);
    const msg = res.message;
    
    if (!AppState.messages[AppState.currentConvId]) {
      AppState.messages[AppState.currentConvId] = [];
    }
    AppState.messages[AppState.currentConvId].push(msg);
    renderMessages(AppState.currentConvId);
    scrollToBottom();
    
    // Update conversation list
    updateConvPreview(AppState.currentConvId, msg);
  } catch (e) {
    UI.toast('Failed to send message', 'error');
    input.value = content;
  }
}

function updateConvPreview(convId, msg) {
  const conv = AppState.conversations.find(c => c.id === convId);
  if (conv) {
    conv.last_message = msg;
    conv.updated_at = msg.created_at;
    // Move to top
    AppState.conversations = [
      conv,
      ...AppState.conversations.filter(c => c.id !== convId)
    ];
    renderChatList();
  }
}

// ========== FILE UPLOAD ==========
async function handleFileUpload(files) {
  if (!AppState.currentConvId || !files.length) return;
  
  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('conversation_id', AppState.currentConvId);
    
    try {
      UI.toast('Uploading...', 'info');
      const res = await API.upload('/api/files/upload', formData);
      const msg = res.message;
      
      if (!AppState.messages[AppState.currentConvId]) {
        AppState.messages[AppState.currentConvId] = [];
      }
      AppState.messages[AppState.currentConvId].push(msg);
      renderMessages(AppState.currentConvId);
      scrollToBottom();
      updateConvPreview(AppState.currentConvId, msg);
    } catch (e) {
      UI.toast('Upload failed: ' + (e.data?.error || e.message), 'error');
    }
  }
}

// ========== VOICE RECORDING ==========
async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    AppState.mediaRecorder = new MediaRecorder(stream);
    AppState.recordingChunks = [];
    AppState.recordingStart = Date.now();
    
    AppState.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) AppState.recordingChunks.push(e.data);
    };
    
    AppState.mediaRecorder.start(100);
    
    document.getElementById('inputRow').style.display = 'none';
    document.getElementById('recordingBar').classList.add('show');
    
    // Timer
    AppState.recordingTimer = setInterval(() => {
      const elapsed = (Date.now() - AppState.recordingStart) / 1000;
      document.getElementById('recordingTime').textContent = UI.formatDuration(elapsed);
    }, 200);
  } catch (e) {
    UI.toast('Could not access microphone', 'error');
  }
}

function cancelRecording() {
  if (AppState.mediaRecorder) {
    AppState.mediaRecorder.stop();
    AppState.mediaRecorder.stream.getTracks().forEach(t => t.stop());
    AppState.mediaRecorder = null;
  }
  clearInterval(AppState.recordingTimer);
  document.getElementById('recordingBar').classList.remove('show');
  document.getElementById('inputRow').style.display = 'flex';
  AppState.recordingChunks = [];
}

async function sendRecording() {
  if (!AppState.mediaRecorder) return;
  
  const duration = (Date.now() - AppState.recordingStart) / 1000;
  
  AppState.mediaRecorder.onstop = async () => {
    const blob = new Blob(AppState.recordingChunks, { type: 'audio/webm' });
    const formData = new FormData();
    formData.append('audio', blob, 'voice.webm');
    formData.append('conversation_id', AppState.currentConvId);
    formData.append('duration', duration);
    
    try {
      const res = await API.upload('/api/files/upload/voice', formData);
      const msg = res.message;
      
      if (!AppState.messages[AppState.currentConvId]) {
        AppState.messages[AppState.currentConvId] = [];
      }
      AppState.messages[AppState.currentConvId].push(msg);
      renderMessages(AppState.currentConvId);
      scrollToBottom();
      updateConvPreview(AppState.currentConvId, msg);
    } catch (e) {
      UI.toast('Failed to send voice message', 'error');
    }
  };
  
  AppState.mediaRecorder.stop();
  AppState.mediaRecorder.stream.getTracks().forEach(t => t.stop());
  AppState.mediaRecorder = null;
  clearInterval(AppState.recordingTimer);
  document.getElementById('recordingBar').classList.remove('show');
  document.getElementById('inputRow').style.display = 'flex';
}

// ========== SOCKET HANDLERS ==========
function setupSocketHandlers() {
  SocketManager.on('new_message', (msg) => {
    if (!msg) return;
    
    const convId = msg.conversation_id;
    
    if (!AppState.messages[convId]) AppState.messages[convId] = [];
    
    // Avoid duplicates
    if (AppState.messages[convId].find(m => m.id === msg.id)) return;
    
    AppState.messages[convId].push(msg);
    
    if (convId === AppState.currentConvId) {
      renderMessages(convId);
      scrollToBottom();
      SocketManager.messagesRead(convId, [msg.id]);
      SocketManager.messageDelivered(msg.id, convId);
    } else {
      // Update unread
      const conv = AppState.conversations.find(c => c.id === convId);
      if (conv) {
        conv.unread_count = (conv.unread_count || 0) + 1;
      }
    }
    
    updateConvPreview(convId, msg);
    
    // Notification
    if (msg.sender_id !== AppState.user.id && document.hidden) {
      showNotification(msg);
    }
  });
  
  SocketManager.on('typing', (data) => {
    if (data.conversation_id === AppState.currentConvId && data.user_id !== AppState.user.id) {
      const el = document.getElementById('typingIndicator');
      if (data.is_typing) {
        el.textContent = data.display_name + ' is typing...';
        el.classList.add('show');
      } else {
        el.classList.remove('show');
      }
    }
  });
  
  SocketManager.on('message_status', (data) => {
    const msgs = AppState.messages[data.conversation_id];
    if (msgs) {
      const msg = msgs.find(m => m.id === data.message_id);
      if (msg) {
        msg.status = data.status;
        if (data.conversation_id === AppState.currentConvId) {
          renderMessages(data.conversation_id);
        }
      }
    }
  });
  
  SocketManager.on('user_online', (data) => {
    AppState.conversations.forEach(c => {
      if (c.other_user?.id === data.user_id) {
        c.other_user.is_online = true;
        c.is_online = true;
      }
    });
    renderChatList();
    if (AppState.currentConvId) {
      const conv = AppState.conversations.find(c => c.id === AppState.currentConvId);
      if (conv?.other_user?.id === data.user_id) {
        document.getElementById('convStatus').textContent = 'Online';
        document.getElementById('convStatus').classList.add('online');
      }
    }
  });
  
  SocketManager.on('user_offline', (data) => {
    AppState.conversations.forEach(c => {
      if (c.other_user?.id === data.user_id) {
        c.other_user.is_online = false;
        c.is_online = false;
      }
    });
    renderChatList();
  });
  
  SocketManager.on('incoming_call', (data) => {
    showIncomingCall(data);
  });
  
  SocketManager.on('call_ended', () => {
    hideCallUI();
    WebRTCManager.cleanup();
  });
  
  SocketManager.on('call_rejected', () => {
    hideCallUI();
    WebRTCManager.cleanup();
    UI.toast('Call rejected', 'info');
  });
  
  SocketManager.on('webrtc_offer', (data) => WebRTCManager.handleOffer(data));
  SocketManager.on('webrtc_answer', (data) => WebRTCManager.handleAnswer(data));
  SocketManager.on('webrtc_ice', (data) => WebRTCManager.handleIce(data));
}

// ========== CALLS ==========
function showIncomingCall(data) {
  const overlay = document.getElementById('callOverlay');
  overlay.classList.add('active');
  
  const caller = data.caller || {};
  document.getElementById('callName').textContent = caller.display_name || 'Incoming call';
  document.getElementById('callStatusText').textContent = data.call?.call_type === 'video' ? 'Incoming video call' : 'Incoming voice call';
  document.getElementById('callAvatar').innerHTML = caller.profile_photo
    ? `<img src="/uploads/${caller.profile_photo}">`
    : UI.getInitials(caller.display_name);
  
  document.getElementById('btnAcceptCall').style.display = 'flex';
  document.getElementById('btnCamera').style.display = data.call?.call_type === 'video' ? 'flex' : 'none';
  
  if (data.call?.call_type === 'video') {
    overlay.classList.add('video-mode');
  }
  
  WebRTCManager.currentCall = data.call;
  
  document.getElementById('btnAcceptCall').onclick = async () => {
    document.getElementById('btnAcceptCall').style.display = 'none';
    document.getElementById('callStatusText').textContent = 'Connecting...';
    try {
      await WebRTCManager.answerCall(data.call);
    } catch (e) {
      UI.toast('Failed to answer call', 'error');
      hideCallUI();
    }
  };
}

function hideCallUI() {
  const overlay = document.getElementById('callOverlay');
  overlay.classList.remove('active', 'video-mode');
  document.getElementById('btnAcceptCall').style.display = 'none';
}

async function startVoiceCall() {
  const conv = AppState.conversations.find(c => c.id === AppState.currentConvId);
  if (!conv || conv.type !== 'private') {
    UI.toast('Voice calls are available for private chats', 'info');
    return;
  }
  
  const overlay = document.getElementById('callOverlay');
  overlay.classList.add('active');
  document.getElementById('callName').textContent = conv.other_user?.display_name || 'User';
  document.getElementById('callStatusText').textContent = 'Calling...';
  document.getElementById('callAvatar').innerHTML = conv.other_user?.profile_photo
    ? `<img src="/uploads/${conv.other_user.profile_photo}">`
    : UI.getInitials(conv.other_user?.display_name);
  document.getElementById('btnCamera').style.display = 'none';
  document.getElementById('btnAcceptCall').style.display = 'none';
  
  try {
    await WebRTCManager.startCall(conv.other_user.id, conv.id, 'voice');
  } catch (e) {
    UI.toast(e.message || 'Failed to start call', 'error');
    hideCallUI();
  }
}

async function startVideoCall() {
  const conv = AppState.conversations.find(c => c.id === AppState.currentConvId);
  if (!conv || conv.type !== 'private') {
    UI.toast('Video calls are available for private chats', 'info');
    return;
  }
  
  const overlay = document.getElementById('callOverlay');
  overlay.classList.add('active', 'video-mode');
  document.getElementById('callName').textContent = conv.other_user?.display_name || 'User';
  document.getElementById('callStatusText').textContent = 'Calling...';
  document.getElementById('btnCamera').style.display = 'flex';
  document.getElementById('btnAcceptCall').style.display = 'none';
  
  try {
    await WebRTCManager.startCall(conv.other_user.id, conv.id, 'video');
  } catch (e) {
    UI.toast(e.message || 'Failed to start call', 'error');
    hideCallUI();
  }
}

// ========== SEARCH ==========
let searchTimeout;
async function handleSearch(query) {
  const results = document.getElementById('searchResults');
  if (query.length < 2) {
    results.classList.remove('open');
    return;
  }
  
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(async () => {
    try {
      const res = await API.get(`/api/chats/search?q=${encodeURIComponent(query)}`);
      let html = '';
      
      if (res.users?.length) {
        html += res.users.map(u => `
          <div class="search-result-item" onclick="startChatWith(${u.id})">
            ${UI.avatarHtml(u)}
            <div>
              <div style="font-weight:500;font-size:14px;">${UI.escapeHtml(u.display_name)}</div>
              <div style="font-size:12px;color:var(--text-tertiary);">@${UI.escapeHtml(u.username)}</div>
            </div>
          </div>
        `).join('');
      }
      
      if (res.conversations?.length) {
        html += res.conversations.map(c => `
          <div class="search-result-item" onclick="openConversation(${c.id});document.getElementById('searchResults').classList.remove('open');">
            <div class="avatar">${UI.getInitials(c.name)}</div>
            <div>
              <div style="font-weight:500;font-size:14px;">${UI.escapeHtml(c.name)}</div>
              <div style="font-size:12px;color:var(--text-tertiary);">Group</div>
            </div>
          </div>
        `).join('');
      }
      
      if (!html) html = '<div style="padding:16px;text-align:center;color:var(--text-tertiary);font-size:13px;">No results found</div>';
      
      results.innerHTML = html;
      results.classList.add('open');
    } catch (e) {}
  }, 300);
}

async function startChatWith(userId) {
  document.getElementById('searchResults').classList.remove('open');
  document.getElementById('globalSearch').value = '';
  
  try {
    const res = await API.post('/api/chats/private', { user_id: userId });
    const conv = res.conversation;
    
    // Add to list if new
    if (!AppState.conversations.find(c => c.id === conv.id)) {
      AppState.conversations.unshift(conv);
      renderChatList();
    }
    
    openConversation(conv.id);
  } catch (e) {
    UI.toast(e.data?.error || 'Failed to start chat', 'error');
  }
}

// ========== NEW GROUP ==========
function showNewGroupModal() {
  UI.showModal('New Group', `
    <div class="form-group">
      <label>Group Name</label>
      <input type="text" id="groupName" placeholder="Enter group name" maxlength="200">
    </div>
    <div class="form-group">
      <label>Description (optional)</label>
      <textarea id="groupDesc" placeholder="Group description" maxlength="1000"></textarea>
    </div>
  `, `
    <button class="btn btn-secondary" onclick="UI.hideModal()">Cancel</button>
    <button class="btn btn-primary" onclick="createGroup()">Create</button>
  `);
}

async function createGroup() {
  const name = document.getElementById('groupName').value.trim();
  if (!name) { UI.toast('Group name required', 'error'); return; }
  
  try {
    const res = await API.post('/api/groups/', {
      name,
      description: document.getElementById('groupDesc').value.trim()
    });
    UI.hideModal();
    AppState.conversations.unshift(res.conversation);
    renderChatList();
    openConversation(res.conversation.id);
    UI.toast('Group created', 'success');
  } catch (e) {
    UI.toast(e.data?.error || 'Failed to create group', 'error');
  }
}

// ========== SETTINGS ==========
function showSettings() {
  UI.showModal('Settings', `
    <div class="settings-group">
      <h3>Account</h3>
      <div class="settings-item">
        <div>
          <div class="settings-item-label">${UI.escapeHtml(AppState.user.display_name)}</div>
          <div class="settings-item-desc">@${UI.escapeHtml(AppState.user.username)} &middot; ${UI.escapeHtml(AppState.user.email)}</div>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="showEditProfile()">Edit</button>
      </div>
    </div>
    <div class="settings-group">
      <h3>Appearance</h3>
      <div class="settings-item">
        <div class="settings-item-label">Theme</div>
        <select id="themeSelect" onchange="changeTheme(this.value)" style="width:auto;padding:6px 12px;">
          <option value="light" ${AppState.user.theme==='light'?'selected':''}>Light</option>
          <option value="dark" ${AppState.user.theme==='dark'?'selected':''}>Dark</option>
          <option value="system" ${AppState.user.theme==='system'||!AppState.user.theme?'selected':''}>System</option>
        </select>
      </div>
    </div>
    <div class="settings-group">
      <h3>Notifications</h3>
      <div class="settings-item">
        <div class="settings-item-label">Message notifications</div>
        <label class="toggle"><input type="checkbox" id="notifMsg" ${AppState.user.notify_messages?'checked':''} onchange="updateNotif('notify_messages',this.checked)"><span class="slider"></span></label>
      </div>
      <div class="settings-item">
        <div class="settings-item-label">Call notifications</div>
        <label class="toggle"><input type="checkbox" id="notifCall" ${AppState.user.notify_calls?'checked':''} onchange="updateNotif('notify_calls',this.checked)"><span class="slider"></span></label>
      </div>
    </div>
    <div class="settings-group">
      <h3>Account Actions</h3>
      <div class="settings-item">
        <div class="settings-item-label">Change password</div>
        <button class="btn btn-secondary btn-sm" onclick="showChangePassword()">Change</button>
      </div>
      <div class="settings-item">
        <div class="settings-item-label" style="color:var(--error);">Log out</div>
        <button class="btn btn-danger btn-sm" onclick="logout()">Log out</button>
      </div>
    </div>
  `);
}

function changeTheme(theme) {
  UI.applyTheme(theme);
  API.put('/api/users/profile', { theme }).catch(() => {});
  AppState.user.theme = theme;
}

async function updateNotif(field, value) {
  try {
    await API.put('/api/notifications/settings', { [field]: value });
    AppState.user[field] = value;
  } catch (e) {}
}

function showEditProfile() {
  UI.showModal('Edit Profile', `
    <div class="form-group">
      <label>Display Name</label>
      <input type="text" id="editDisplayName" value="${UI.escapeHtml(AppState.user.display_name)}" maxlength="100">
    </div>
    <div class="form-group">
      <label>Username</label>
      <input type="text" id="editUsername" value="${UI.escapeHtml(AppState.user.username)}" maxlength="30">
    </div>
    <div class="form-group">
      <label>Bio</label>
      <textarea id="editBio" maxlength="500">${UI.escapeHtml(AppState.user.bio || '')}</textarea>
    </div>
  `, `
    <button class="btn btn-secondary" onclick="UI.hideModal()">Cancel</button>
    <button class="btn btn-primary" onclick="saveProfile()">Save</button>
  `);
}

async function saveProfile() {
  try {
    const res = await API.put('/api/users/profile', {
      display_name: document.getElementById('editDisplayName').value.trim(),
      username: document.getElementById('editUsername').value.trim(),
      bio: document.getElementById('editBio').value.trim()
    });
    AppState.user = res.user;
    UI.hideModal();
    UI.toast('Profile updated', 'success');
  } catch (e) {
    UI.toast(e.data?.error || 'Failed to update', 'error');
  }
}

function showChangePassword() {
  UI.showModal('Change Password', `
    <div class="form-group">
      <label>Current Password</label>
      <input type="password" id="currentPw">
    </div>
    <div class="form-group">
      <label>New Password</label>
      <input type="password" id="newPw" minlength="8">
    </div>
  `, `
    <button class="btn btn-secondary" onclick="UI.hideModal()">Cancel</button>
    <button class="btn btn-primary" onclick="doChangePassword()">Change</button>
  `);
}

async function doChangePassword() {
  try {
    await API.post('/api/auth/change-password', {
      current_password: document.getElementById('currentPw').value,
      new_password: document.getElementById('newPw').value
    });
    UI.hideModal();
    UI.toast('Password changed', 'success');
  } catch (e) {
    UI.toast(e.data?.error || 'Failed', 'error');
  }
}

async function logout() {
  try {
    await API.post('/api/auth/logout');
  } catch (e) {}
  window.location.href = '/';
}

// ========== NOTIFICATIONS ==========
function showNotification(msg) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  
  const title = msg.sender?.display_name || 'ESTACLE';
  const body = msg.content || (msg.message_type !== 'text' ? msg.message_type : 'New message');
  
  new Notification(title, {
    body,
    icon: '/static/icons/icon-192.png',
    tag: 'estacle-' + msg.conversation_id
  });
}

async function requestNotificationPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    await Notification.requestPermission();
  }
}

// ========== ONLINE/OFFLINE ==========
function handleOnline() {
  document.getElementById('offlineBanner').classList.remove('show');
  // Flush offline queue
  while (AppState.offlineQueue.length) {
    const item = AppState.offlineQueue.shift();
    API.post(`/api/messages/${item.convId}`, item.data).catch(() => {});
  }
  localStorage.setItem('estacle-offline-queue', '[]');
}

function handleOffline() {
  document.getElementById('offlineBanner').classList.add('show');
}

// ========== EVENT LISTENERS ==========
function setupEventListeners() {
  // Send message
  document.getElementById('btnSend').addEventListener('click', sendMessage);
  document.getElementById('messageInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });
  
  // Auto-resize textarea
  const input = document.getElementById('messageInput');
  input.addEventListener('input', () => {
    autoResize(input);
    document.getElementById('btnSend').disabled = !input.value.trim();
    
    // Typing indicator
    if (AppState.currentConvId && input.value.trim()) {
      SocketManager.typingStart(AppState.currentConvId);
      clearTimeout(AppState.typingTimeout);
      AppState.typingTimeout = setTimeout(() => {
        SocketManager.typingStop(AppState.currentConvId);
      }, 2000);
    }
  });
  
  // Attach file
  document.getElementById('btnAttach').addEventListener('click', () => {
    document.getElementById('fileInput').click();
  });
  document.getElementById('fileInput').addEventListener('change', (e) => {
    handleFileUpload(Array.from(e.target.files));
    e.target.value = '';
  });
  
  // Voice recording
  document.getElementById('btnVoice').addEventListener('click', startRecording);
  document.getElementById('cancelRecording').addEventListener('click', cancelRecording);
  document.getElementById('sendRecording').addEventListener('click', sendRecording);
  
  // Back button (mobile)
  document.getElementById('btnBack').addEventListener('click', () => {
    document.getElementById('sidebar').classList.remove('hidden-mobile');
    document.getElementById('conversationPanel').classList.add('hidden-mobile');
    if (AppState.currentConvId) {
      SocketManager.leaveConversation(AppState.currentConvId);
    }
    AppState.currentConvId = null;
  });
  
  // Calls
  document.getElementById('btnVoiceCall').addEventListener('click', startVoiceCall);
  document.getElementById('btnVideoCall').addEventListener('click', startVideoCall);
  document.getElementById('btnEndCall').addEventListener('click', async () => {
    await WebRTCManager.endCall();
    hideCallUI();
  });
  document.getElementById('btnMute').addEventListener('click', () => {
    const muted = WebRTCManager.toggleMute();
    document.getElementById('btnMute').classList.toggle('active', muted);
  });
  document.getElementById('btnCamera').addEventListener('click', () => {
    const off = WebRTCManager.toggleCamera();
    document.getElementById('btnCamera').classList.toggle('active', off);
  });
  
  // Search
  document.getElementById('globalSearch').addEventListener('input', (e) => {
    handleSearch(e.target.value.trim());
  });
  document.getElementById('globalSearch').addEventListener('blur', () => {
    setTimeout(() => document.getElementById('searchResults').classList.remove('open'), 200);
  });
  
  // New chat / group / settings
  document.getElementById('btnNewChat').addEventListener('click', () => {
    document.getElementById('globalSearch').focus();
  });
  document.getElementById('btnNewGroup').addEventListener('click', showNewGroupModal);
  document.getElementById('btnSettings').addEventListener('click', showSettings);
  
  // Close reply
  document.getElementById('closeReply').addEventListener('click', () => {
    AppState.replyTo = null;
    document.getElementById('replyPreview').classList.remove('show');
  });
  
  // Info panel
  document.getElementById('btnConvInfo')?.addEventListener('click', showConvInfo);
  document.getElementById('closeInfoPanel')?.addEventListener('click', () => {
    document.getElementById('infoPanel').classList.remove('open');
  });
  
  // Drag and drop
  document.body.addEventListener('dragover', (e) => { e.preventDefault(); });
  document.body.addEventListener('drop', (e) => {
    e.preventDefault();
    if (AppState.currentConvId && e.dataTransfer.files.length) {
      handleFileUpload(Array.from(e.dataTransfer.files));
    }
  });
  
  // Paste images
  document.addEventListener('paste', (e) => {
    if (!AppState.currentConvId) return;
    const items = e.clipboardData?.items;
    if (!items) return;
    const files = [];
    for (const item of items) {
      if (item.type.startsWith('image/')) {
        files.push(item.getAsFile());
      }
    }
    if (files.length) handleFileUpload(files);
  });
  
  // Request notification permission
  requestNotificationPermission();
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function showConvInfo() {
  const conv = AppState.conversations.find(c => c.id === AppState.currentConvId);
  if (!conv) return;
  
  const panel = document.getElementById('infoPanel');
  const content = document.getElementById('infoPanelContent');
  
  const name = conv.name || conv.other_user?.display_name || 'Chat';
  const photo = conv.photo || conv.other_user?.profile_photo;
  
  content.innerHTML = `
    <div class="info-profile">
      <div class="avatar">
        ${photo ? `<img src="/uploads/${photo}">` : UI.getInitials(name)}
      </div>
      <h2>${UI.escapeHtml(name)}</h2>
      ${conv.other_user ? `<div class="username">@${UI.escapeHtml(conv.other_user.username)}</div>` : ''}
      ${conv.description ? `<div class="bio">${UI.escapeHtml(conv.description)}</div>` : ''}
      ${conv.other_user?.bio ? `<div class="bio">${UI.escapeHtml(conv.other_user.bio)}</div>` : ''}
    </div>
    <div class="info-section">
      <h4>Actions</h4>
      <button class="btn btn-secondary btn-sm" style="width:100%;margin-bottom:8px;" onclick="togglePin(${conv.id})">
        ${conv.is_pinned ? 'Unpin Chat' : 'Pin Chat'}
      </button>
      <button class="btn btn-secondary btn-sm" style="width:100%;margin-bottom:8px;" onclick="toggleMute(${conv.id})">
        ${conv.is_muted ? 'Unmute' : 'Mute'}
      </button>
      <button class="btn btn-danger btn-sm" style="width:100%;" onclick="deleteChat(${conv.id})">Delete Chat</button>
    </div>
  `;
  
  panel.classList.add('open');
}

async function togglePin(convId) {
  const conv = AppState.conversations.find(c => c.id === convId);
  if (!conv) return;
  try {
    await API.put(`/api/chats/${convId}/settings`, { is_pinned: !conv.is_pinned });
    conv.is_pinned = !conv.is_pinned;
    renderChatList();
    showConvInfo();
  } catch (e) {}
}

async function toggleMute(convId) {
  const conv = AppState.conversations.find(c => c.id === convId);
  if (!conv) return;
  try {
    await API.put(`/api/chats/${convId}/settings`, { is_muted: !conv.is_muted });
    conv.is_muted = !conv.is_muted;
    showConvInfo();
  } catch (e) {}
}

async function deleteChat(convId) {
  if (!await UI.confirm('Delete Chat', 'Are you sure you want to delete this chat?')) return;
  try {
    await API.delete(`/api/chats/${convId}`);
    AppState.conversations = AppState.conversations.filter(c => c.id !== convId);
    renderChatList();
    document.getElementById('infoPanel').classList.remove('open');
    document.getElementById('activeConversation').style.display = 'none';
    document.getElementById('welcomeScreen').style.display = 'flex';
    AppState.currentConvId = null;
  } catch (e) {
    UI.toast('Failed to delete', 'error');
  }
}

// Message context menu
function showMessageMenu(e, msgId) {
  e.preventDefault();
  // Simplified - can expand later
}

// Start
document.addEventListener('DOMContentLoaded', initApp);
