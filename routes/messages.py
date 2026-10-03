from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
from sqlalchemy import and_, or_, desc
import os
import uuid

from database.database import get_db
from database.models import (
    Message, Attachment, MessageReaction, MessageDeletion,
    Conversation, SavedMessage, conversation_members, User
)

messages_bp = Blueprint('messages', __name__)

@messages_bp.route('/<int:conv_id>', methods=['GET'])
@login_required
def get_messages(conv_id):
    before_id = request.args.get('before_id', type=int)
    after_id = request.args.get('after_id', type=int)
    limit = min(int(request.args.get('limit', 40)), 100)
    
    db = get_db()
    try:
        # Verify membership
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == conv_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Not a member'}), 403
        
        query = db.query(Message).filter(Message.conversation_id == conv_id)
        
        if before_id:
            query = query.filter(Message.id < before_id)
        if after_id:
            query = query.filter(Message.id > after_id)
        
        messages = query.order_by(Message.created_at.desc()).limit(limit).all()
        messages.reverse()  # chronological order
        
        result = []
        for m in messages:
            d = m.to_dict(current_user.id)
            if d:
                result.append(d)
        
        return jsonify({
            'messages': result,
            'has_more': len(messages) == limit
        })
    finally:
        db.close()


@messages_bp.route('/<int:conv_id>', methods=['POST'])
@login_required
def send_message(conv_id):
    data = request.get_json() or {}
    
    content = (data.get('content') or '').strip()
    message_type = data.get('message_type', 'text')
    reply_to_id = data.get('reply_to_id')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    location_name = data.get('location_name')
    shared_contact_id = data.get('shared_contact_id')
    
    if message_type == 'text' and not content:
        return jsonify({'error': 'Message content required'}), 400
    
    db = get_db()
    try:
        # Verify membership
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == conv_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Not a member'}), 403
        
        conv = db.query(Conversation).get(conv_id)
        if not conv or not conv.is_active:
            return jsonify({'error': 'Conversation not found'}), 404
        
        # Check admin-only posting for groups
        if conv.type == 'group' and conv.only_admins_can_post:
            if member.role not in ('admin', 'owner'):
                return jsonify({'error': 'Only admins can post in this group'}), 403
        
        msg = Message(
            conversation_id=conv_id,
            sender_id=current_user.id,
            content=content if content else None,
            message_type=message_type,
            reply_to_id=reply_to_id,
            status='sent',
            latitude=latitude,
            longitude=longitude,
            location_name=location_name,
            shared_contact_id=shared_contact_id,
        )
        db.add(msg)
        
        # Update conversation timestamp
        conv.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(msg)
        
        result = msg.to_dict(current_user.id)
        
        # Emit via WebSocket (handled in realtime)
        from flask import current_app
        try:
            from app import socketio
            socketio.emit('new_message', result, room=f'conversation_{conv_id}')
        except Exception:
            pass
        
        return jsonify({'message': result}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to send message', 'detail': str(e)}), 500
    finally:
        db.close()


@messages_bp.route('/<int:msg_id>', methods=['PUT'])
@login_required
def edit_message(msg_id):
    data = request.get_json() or {}
    content = (data.get('content') or '').strip()
    
    if not content:
        return jsonify({'error': 'Content required'}), 400
    
    db = get_db()
    try:
        msg = db.query(Message).get(msg_id)
        if not msg or msg.sender_id != current_user.id:
            return jsonify({'error': 'Message not found'}), 404
        
        if msg.is_deleted_for_everyone:
            return jsonify({'error': 'Cannot edit deleted message'}), 400
        
        msg.content = content
        msg.is_edited = True
        msg.edited_at = datetime.now(timezone.utc)
        msg.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        result = msg.to_dict(current_user.id)
        
        try:
            from app import socketio
            socketio.emit('message_edited', result, room=f'conversation_{msg.conversation_id}')
        except Exception:
            pass
        
        return jsonify({'message': result})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to edit message'}), 500
    finally:
        db.close()


@messages_bp.route('/<int:msg_id>', methods=['DELETE'])
@login_required
def delete_message(msg_id):
    data = request.get_json() or {}
    delete_for = data.get('for', 'me')  # me or everyone
    
    db = get_db()
    try:
        msg = db.query(Message).get(msg_id)
        if not msg:
            return jsonify({'error': 'Message not found'}), 404
        
        # Verify membership
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == msg.conversation_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Not authorized'}), 403
        
        if delete_for == 'everyone':
            if msg.sender_id != current_user.id:
                return jsonify({'error': 'Can only delete your own messages for everyone'}), 403
            msg.is_deleted_for_everyone = True
            msg.content = None
            db.commit()
            
            try:
                from app import socketio
                socketio.emit('message_deleted', {
                    'message_id': msg_id,
                    'conversation_id': msg.conversation_id,
                    'for': 'everyone'
                }, room=f'conversation_{msg.conversation_id}')
            except Exception:
                pass
        else:
            # Delete for me
            existing = db.query(MessageDeletion).filter(
                MessageDeletion.message_id == msg_id,
                MessageDeletion.user_id == current_user.id
            ).first()
            if not existing:
                deletion = MessageDeletion(message_id=msg_id, user_id=current_user.id)
                db.add(deletion)
                db.commit()
        
        return jsonify({'message': 'Message deleted'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to delete message'}), 500
    finally:
        db.close()


@messages_bp.route('/<int:msg_id>/react', methods=['POST'])
@login_required
def react_to_message(msg_id):
    data = request.get_json() or {}
    reaction = (data.get('reaction') or '').strip()
    
    if not reaction or len(reaction) > 50:
        return jsonify({'error': 'Invalid reaction'}), 400
    
    db = get_db()
    try:
        msg = db.query(Message).get(msg_id)
        if not msg:
            return jsonify({'error': 'Message not found'}), 404
        
        # Check membership
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == msg.conversation_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Not authorized'}), 403
        
        # Toggle reaction
        existing = db.query(MessageReaction).filter(
            MessageReaction.message_id == msg_id,
            MessageReaction.user_id == current_user.id,
            MessageReaction.reaction == reaction
        ).first()
        
        if existing:
            db.delete(existing)
            action = 'removed'
        else:
            # Remove other reactions by same user (one reaction per user)
            db.query(MessageReaction).filter(
                MessageReaction.message_id == msg_id,
                MessageReaction.user_id == current_user.id
            ).delete()
            
            r = MessageReaction(
                message_id=msg_id,
                user_id=current_user.id,
                reaction=reaction
            )
            db.add(r)
            action = 'added'
        
        db.commit()
        
        # Get all reactions
        reactions = db.query(MessageReaction).filter(
            MessageReaction.message_id == msg_id
        ).all()
        
        result = {
            'message_id': msg_id,
            'conversation_id': msg.conversation_id,
            'action': action,
            'reaction': reaction,
            'user_id': current_user.id,
            'reactions': [r.to_dict() for r in reactions]
        }
        
        try:
            from app import socketio
            socketio.emit('message_reaction', result, room=f'conversation_{msg.conversation_id}')
        except Exception:
            pass
        
        return jsonify(result)
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to react'}), 500
    finally:
        db.close()


@messages_bp.route('/<int:msg_id>/pin', methods=['POST'])
@login_required
def pin_message(msg_id):
    data = request.get_json() or {}
    pinned = data.get('pinned', True)
    
    db = get_db()
    try:
        msg = db.query(Message).get(msg_id)
        if not msg:
            return jsonify({'error': 'Message not found'}), 404
        
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == msg.conversation_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Not authorized'}), 403
        
        msg.is_pinned = bool(pinned)
        db.commit()
        
        try:
            from app import socketio
            socketio.emit('message_pinned', {
                'message_id': msg_id,
                'conversation_id': msg.conversation_id,
                'is_pinned': msg.is_pinned
            }, room=f'conversation_{msg.conversation_id}')
        except Exception:
            pass
        
        return jsonify({'message': 'Pinned' if pinned else 'Unpinned', 'is_pinned': msg.is_pinned})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@messages_bp.route('/<int:msg_id>/forward', methods=['POST'])
@login_required
def forward_message(msg_id):
    data = request.get_json() or {}
    target_conv_id = data.get('conversation_id')
    
    if not target_conv_id:
        return jsonify({'error': 'conversation_id required'}), 400
    
    db = get_db()
    try:
        original = db.query(Message).get(msg_id)
        if not original or original.is_deleted_for_everyone:
            return jsonify({'error': 'Message not found'}), 404
        
        # Verify membership in both
        for cid in [original.conversation_id, target_conv_id]:
            member = db.execute(
                conversation_members.select().where(
                    and_(
                        conversation_members.c.conversation_id == cid,
                        conversation_members.c.user_id == current_user.id
                    )
                )
            ).first()
            if not member:
                return jsonify({'error': 'Not authorized'}), 403
        
        new_msg = Message(
            conversation_id=target_conv_id,
            sender_id=current_user.id,
            content=original.content,
            message_type=original.message_type,
            forwarded_from_id=original.id,
            status='sent',
            latitude=original.latitude,
            longitude=original.longitude,
            location_name=original.location_name,
        )
        db.add(new_msg)
        db.flush()
        
        # Copy attachments
        for att in original.attachments:
            new_att = Attachment(
                message_id=new_msg.id,
                filename=att.filename,
                original_filename=att.original_filename,
                file_path=att.file_path,
                file_type=att.file_type,
                mime_type=att.mime_type,
                file_size=att.file_size,
                duration=att.duration,
                width=att.width,
                height=att.height,
                thumbnail_path=att.thumbnail_path,
            )
            db.add(new_att)
        
        conv = db.query(Conversation).get(target_conv_id)
        if conv:
            conv.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(new_msg)
        
        result = new_msg.to_dict(current_user.id)
        
        try:
            from app import socketio
            socketio.emit('new_message', result, room=f'conversation_{target_conv_id}')
        except Exception:
            pass
        
        return jsonify({'message': result}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to forward', 'detail': str(e)}), 500
    finally:
        db.close()


@messages_bp.route('/saved', methods=['GET'])
@login_required
def list_saved():
    db = get_db()
    try:
        saved = db.query(SavedMessage).filter(
            SavedMessage.user_id == current_user.id
        ).order_by(SavedMessage.saved_at.desc()).all()
        
        result = []
        for s in saved:
            if s.message:
                d = s.message.to_dict(current_user.id)
                if d:
                    d['saved_at'] = s.saved_at.isoformat() if s.saved_at else None
                    d['saved_id'] = s.id
                    result.append(d)
        
        return jsonify({'saved': result})
    finally:
        db.close()


@messages_bp.route('/saved', methods=['POST'])
@login_required
def save_message():
    data = request.get_json() or {}
    message_id = data.get('message_id')
    
    if not message_id:
        return jsonify({'error': 'message_id required'}), 400
    
    db = get_db()
    try:
        msg = db.query(Message).get(message_id)
        if not msg:
            return jsonify({'error': 'Message not found'}), 404
        
        existing = db.query(SavedMessage).filter(
            SavedMessage.user_id == current_user.id,
            SavedMessage.message_id == message_id
        ).first()
        
        if existing:
            return jsonify({'message': 'Already saved', 'saved_id': existing.id})
        
        saved = SavedMessage(
            user_id=current_user.id,
            message_id=message_id,
            note=data.get('note')
        )
        db.add(saved)
        db.commit()
        
        return jsonify({'message': 'Message saved', 'saved_id': saved.id}), 201
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to save'}), 500
    finally:
        db.close()


@messages_bp.route('/saved/<int:saved_id>', methods=['DELETE'])
@login_required
def unsave_message(saved_id):
    db = get_db()
    try:
        saved = db.query(SavedMessage).filter(
            SavedMessage.id == saved_id,
            SavedMessage.user_id == current_user.id
        ).first()
        
        if not saved:
            return jsonify({'error': 'Not found'}), 404
        
        db.delete(saved)
        db.commit()
        return jsonify({'message': 'Removed from saved'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@messages_bp.route('/search/<int:conv_id>', methods=['GET'])
@login_required
def search_in_conversation(conv_id):
    query = (request.args.get('q') or '').strip()
    if len(query) < 1:
        return jsonify({'messages': []})
    
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == conv_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Not authorized'}), 403
        
        messages = db.query(Message).filter(
            Message.conversation_id == conv_id,
            Message.is_deleted_for_everyone == False,
            Message.content.ilike(f'%{query}%')
        ).order_by(Message.created_at.desc()).limit(50).all()
        
        result = [m.to_dict(current_user.id) for m in messages if m.to_dict(current_user.id)]
        return jsonify({'messages': result})
    finally:
        db.close()
