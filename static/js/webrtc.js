const WebRTCManager = {
  pc: null,
  localStream: null,
  remoteStream: null,
  currentCall: null,
  isMuted: false,
  isCameraOff: false,
  iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
  
  async init() {
    try {
      const res = await API.get('/api/calls/config');
      if (res.iceServers) this.iceServers = res.iceServers;
    } catch (e) {}
  },
  
  async startCall(userId, convId, type = 'voice') {
    try {
      const res = await API.post('/api/calls/start', {
        user_id: userId,
        conversation_id: convId,
        call_type: type
      });
      
      this.currentCall = res.call;
      await this._setupLocalMedia(type === 'video');
      this._createPeerConnection();
      
      const offer = await this.pc.createOffer();
      await this.pc.setLocalDescription(offer);
      
      // Find target user
      const targetId = this.currentCall.participants?.find(p => p.user_id !== AppState.user.id)?.user_id;
      
      SocketManager.sendWebRTC('webrtc_offer', {
        target_user_id: targetId,
        call_id: this.currentCall.id,
        offer: offer
      });
      
      return this.currentCall;
    } catch (e) {
      this.cleanup();
      throw e;
    }
  },
  
  async answerCall(call) {
    this.currentCall = call;
    await this._setupLocalMedia(call.call_type === 'video');
    this._createPeerConnection();
    
    await API.post(`/api/calls/${call.id}/answer`);
  },
  
  async handleOffer(data) {
    if (!this.pc) {
      await this._setupLocalMedia(this.currentCall?.call_type === 'video');
      this._createPeerConnection();
    }
    
    await this.pc.setRemoteDescription(new RTCSessionDescription(data.offer));
    const answer = await this.pc.createAnswer();
    await this.pc.setLocalDescription(answer);
    
    SocketManager.sendWebRTC('webrtc_answer', {
      target_user_id: data.from_user_id,
      call_id: data.call_id,
      answer: answer
    });
  },
  
  async handleAnswer(data) {
    if (this.pc) {
      await this.pc.setRemoteDescription(new RTCSessionDescription(data.answer));
    }
  },
  
  async handleIce(data) {
    if (this.pc && data.candidate) {
      try {
        await this.pc.addIceCandidate(new RTCIceCandidate(data.candidate));
      } catch (e) {}
    }
  },
  
  async _setupLocalMedia(video = false) {
    try {
      this.localStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
        video: video ? { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } } : false
      });
      
      const localVideo = document.getElementById('localVideo');
      if (localVideo && video) {
        localVideo.srcObject = this.localStream;
      }
    } catch (e) {
      console.error('Media access error:', e);
      throw new Error('Could not access microphone/camera');
    }
  },
  
  _createPeerConnection() {
    this.pc = new RTCPeerConnection({ iceServers: this.iceServers });
    
    if (this.localStream) {
      this.localStream.getTracks().forEach(track => {
        this.pc.addTrack(track, this.localStream);
      });
    }
    
    this.pc.ontrack = (event) => {
      this.remoteStream = event.streams[0];
      const remoteVideo = document.getElementById('remoteVideo');
      if (remoteVideo) {
        remoteVideo.srcObject = this.remoteStream;
      }
    };
    
    this.pc.onicecandidate = (event) => {
      if (event.candidate && this.currentCall) {
        const targetId = this.currentCall.participants?.find(
          p => p.user_id !== AppState.user?.id
        )?.user_id;
        
        if (targetId) {
          SocketManager.sendWebRTC('webrtc_ice', {
            target_user_id: targetId,
            call_id: this.currentCall.id,
            candidate: event.candidate
          });
        }
      }
    };
    
    this.pc.onconnectionstatechange = () => {
      if (this.pc.connectionState === 'failed' || this.pc.connectionState === 'disconnected') {
        // Connection issue
      }
    };
  },
  
  toggleMute() {
    if (this.localStream) {
      const audioTrack = this.localStream.getAudioTracks()[0];
      if (audioTrack) {
        audioTrack.enabled = !audioTrack.enabled;
        this.isMuted = !audioTrack.enabled;
      }
    }
    return this.isMuted;
  },
  
  toggleCamera() {
    if (this.localStream) {
      const videoTrack = this.localStream.getVideoTracks()[0];
      if (videoTrack) {
        videoTrack.enabled = !videoTrack.enabled;
        this.isCameraOff = !videoTrack.enabled;
      }
    }
    return this.isCameraOff;
  },
  
  async endCall() {
    if (this.currentCall) {
      try {
        await API.post(`/api/calls/${this.currentCall.id}/end`);
      } catch (e) {}
    }
    this.cleanup();
  },
  
  async rejectCall(callId) {
    try {
      await API.post(`/api/calls/${callId}/reject`);
    } catch (e) {}
    this.cleanup();
  },
  
  cleanup() {
    if (this.localStream) {
      this.localStream.getTracks().forEach(t => t.stop());
      this.localStream = null;
    }
    if (this.pc) {
      this.pc.close();
      this.pc = null;
    }
    this.remoteStream = null;
    this.currentCall = null;
    this.isMuted = false;
    this.isCameraOff = false;
    
    const localVideo = document.getElementById('localVideo');
    const remoteVideo = document.getElementById('remoteVideo');
    if (localVideo) localVideo.srcObject = null;
    if (remoteVideo) remoteVideo.srcObject = null;
  }
};
