from flask import request
from flask_socketio import emit, join_room, leave_room, disconnect
from flask_login import current_user
from datetime import datetime, timezone
import functools

from database.database import get_db
from database.models import User, conversation_members, Message

def authenticated_only(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            disconnect()
            return False
        return f(*args, **kwargs)
    return wrapped

def init_socketio_handlers(socketio):
    
    @socketio.on('connect')
    def handle_connect(auth=None):
        if not current_user.is_authenticated:
            return False
        
        # Join personal room
        join_room(f'user_{current_user.id}')
        
        # Update online status
        db = get_db()
        try:
            user = db.query(User).get(current_user.id)
            if user:
                user.is_online = True
                user.last_seen = datetime.now(timezone.utc)
                db.commit()
                
                # Notify contacts
                emit('user_online', {
                    'user_id': current_user.id,
                    'is_online': True
                }, broadcast=True, include_self=False)
        except Exception:
            db.rollback()
        finally:
            db.close()
        
        emit('connected', {'user_id': current_user.id})
        return True
    
    @socketio.on('disconnect')
    def handle_disconnect():
        if current_user.is_authenticated:
            db = get_db()
            try:
                user = db.query(User).get(current_user.id)
                if user:
                    user.is_online = False
                    user.last_seen = datetime.now(timezone.utc)
                    db.commit()
                    
                    emit('user_offline', {
                        'user_id': current_user.id,
                        'is_online': False,
                        'last_seen': user.last_seen.isoformat()
                    }, broadcast=True, include_self=False)
            except Exception:
                db.rollback()
            finally:
                db.close()
    
    @socketio.on('join_conversation')
    @authenticated_only
    def handle_join_conversation(data):
        conv_id = data.get('conversation_id')
        if not conv_id:
            return
        
        # Verify membership
        db = get_db()
        try:
            member = db.execute(
                conversation_members.select().where(
                    conversation_members.c.conversation_id == conv_id,
                    conversation_members.c.user_id == current_user.id
                )
            ).first()
            
            if member:
                join_room(f'conversation_{conv_id}')
                emit('joined_conversation', {'conversation_id': conv_id})
        finally:
            db.close()
    
    @socketio.on('leave_conversation')
    @authenticated_only
    def handle_leave_conversation(data):
        conv_id = data.get('conversation_id')
        if conv_id:
            leave_room(f'conversation_{conv_id}')
    
    @socketio.on('typing_start')
    @authenticated_only
    def handle_typing_start(data):
        conv_id = data.get('conversation_id')
        if not conv_id:
            return
        
        emit('typing', {
            'conversation_id': conv_id,
            'user_id': current_user.id,
            'display_name': current_user.display_name,
            'is_typing': True
        }, room=f'conversation_{conv_id}', include_self=False)
    
    @socketio.on('typing_stop')
    @authenticated_only
    def handle_typing_stop(data):
        conv_id = data.get('conversation_id')
        if not conv_id:
            return
        
        emit('typing', {
            'conversation_id': conv_id,
            'user_id': current_user.id,
            'display_name': current_user.display_name,
            'is_typing': False
        }, room=f'conversation_{conv_id}', include_self=False)
    
    @socketio.on('message_delivered')
    @authenticated_only
    def handle_message_delivered(data):
        msg_id = data.get('message_id')
        conv_id = data.get('conversation_id')
        
        if not msg_id:
            return
        
        db = get_db()
        try:
            msg = db.query(Message).get(msg_id)
            if msg and msg.status == 'sent':
                msg.status = 'delivered'
                db.commit()
                
                emit('message_status', {
                    'message_id': msg_id,
                    'conversation_id': conv_id or msg.conversation_id,
                    'status': 'delivered'
                }, room=f'user_{msg.sender_id}')
        except Exception:
            db.rollback()
        finally:
            db.close()
    
    @socketio.on('messages_read')
    @authenticated_only
    def handle_messages_read(data):
        conv_id = data.get('conversation_id')
        message_ids = data.get('message_ids', [])
        
        if not conv_id:
            return
        
        db = get_db()
        try:
            # Update last read
            if message_ids:
                max_id = max(message_ids)
                db.execute(
                    conversation_members.update().where(
                        conversation_members.c.conversation_id == conv_id,
                        conversation_members.c.user_id == current_user.id
                    ).values(last_read_message_id=max_id)
                )
                
                # Update message statuses
                messages = db.query(Message).filter(
                    Message.id.in_(message_ids),
                    Message.conversation_id == conv_id,
                    Message.sender_id != current_user.id
                ).all()
                
                for msg in messages:
                    if msg.status in ('sent', 'delivered'):
                        msg.status = 'read'
                        # Notify sender
                        emit('message_status', {
                            'message_id': msg.id,
                            'conversation_id': conv_id,
                            'status': 'read'
                        }, room=f'user_{msg.sender_id}')
                
                db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()
    
    @socketio.on('webrtc_offer')
    @authenticated_only
    def handle_webrtc_offer(data):
        target_user_id = data.get('target_user_id')
        if target_user_id:
            emit('webrtc_offer', {
                'from_user_id': current_user.id,
                'call_id': data.get('call_id'),
                'offer': data.get('offer')
            }, room=f'user_{target_user_id}')
    
    @socketio.on('webrtc_answer')
    @authenticated_only
    def handle_webrtc_answer(data):
        target_user_id = data.get('target_user_id')
        if target_user_id:
            emit('webrtc_answer', {
                'from_user_id': current_user.id,
                'call_id': data.get('call_id'),
                'answer': data.get('answer')
            }, room=f'user_{target_user_id}')
    
    @socketio.on('webrtc_ice')
    @authenticated_only
    def handle_webrtc_ice(data):
        target_user_id = data.get('target_user_id')
        if target_user_id:
            emit('webrtc_ice', {
                'from_user_id': current_user.id,
                'call_id': data.get('call_id'),
                'candidate': data.get('candidate')
            }, room=f'user_{target_user_id}')
    
    @socketio.on('call_signal')
    @authenticated_only
    def handle_call_signal(data):
        target_user_id = data.get('target_user_id')
        if target_user_id:
            emit('call_signal', {
                'from_user_id': current_user.id,
                **{k: v for k, v in data.items() if k != 'target_user_id'}
            }, room=f'user_{target_user_id}')
