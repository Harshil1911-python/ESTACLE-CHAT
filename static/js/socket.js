const SocketManager = {
  socket: null,
  connected: false,
  handlers: {},
  
  connect() {
    if (this.socket) return;
    
    this.socket = io({
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: 20,
      reconnectionDelay: 1000,
    });
    
    this.socket.on('connect', () => {
      this.connected = true;
      this._emit('connected');
      console.log('[WS] Connected');
    });
    
    this.socket.on('disconnect', () => {
      this.connected = false;
      this._emit('disconnected');
      console.log('[WS] Disconnected');
    });
    
    this.socket.on('new_message', (data) => this._emit('new_message', data));
    this.socket.on('message_edited', (data) => this._emit('message_edited', data));
    this.socket.on('message_deleted', (data) => this._emit('message_deleted', data));
    this.socket.on('message_reaction', (data) => this._emit('message_reaction', data));
    this.socket.on('message_status', (data) => this._emit('message_status', data));
    this.socket.on('typing', (data) => this._emit('typing', data));
    this.socket.on('user_online', (data) => this._emit('user_online', data));
    this.socket.on('user_offline', (data) => this._emit('user_offline', data));
    this.socket.on('incoming_call', (data) => this._emit('incoming_call', data));
    this.socket.on('call_answered', (data) => this._emit('call_answered', data));
    this.socket.on('call_rejected', (data) => this._emit('call_rejected', data));
    this.socket.on('call_ended', (data) => this._emit('call_ended', data));
    this.socket.on('webrtc_offer', (data) => this._emit('webrtc_offer', data));
    this.socket.on('webrtc_answer', (data) => this._emit('webrtc_answer', data));
    this.socket.on('webrtc_ice', (data) => this._emit('webrtc_ice', data));
    this.socket.on('webrtc_signal', (data) => this._emit('webrtc_signal', data));
  },
  
  on(event, handler) {
    if (!this.handlers[event]) this.handlers[event] = [];
    this.handlers[event].push(handler);
  },
  
  off(event, handler) {
    if (!this.handlers[event]) return;
    this.handlers[event] = this.handlers[event].filter(h => h !== handler);
  },
  
  _emit(event, data) {
    (this.handlers[event] || []).forEach(h => {
      try { h(data); } catch (e) { console.error(e); }
    });
  },
  
  joinConversation(convId) {
    this.socket?.emit('join_conversation', { conversation_id: convId });
  },
  
  leaveConversation(convId) {
    this.socket?.emit('leave_conversation', { conversation_id: convId });
  },
  
  typingStart(convId) {
    this.socket?.emit('typing_start', { conversation_id: convId });
  },
  
  typingStop(convId) {
    this.socket?.emit('typing_stop', { conversation_id: convId });
  },
  
  messagesRead(convId, messageIds) {
    this.socket?.emit('messages_read', { conversation_id: convId, message_ids: messageIds });
  },
  
  messageDelivered(msgId, convId) {
    this.socket?.emit('message_delivered', { message_id: msgId, conversation_id: convId });
  },
  
  sendWebRTC(event, data) {
    this.socket?.emit(event, data);
  }
};
