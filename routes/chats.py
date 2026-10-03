from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
from datetime import datetime, timezone
from sqlalchemy import and_, or_, func, desc
from sqlalchemy.orm import joinedload

from database.database import get_db
from database.models import (
    User, Conversation, Message, Attachment, UserChatSettings,
    conversation_members, BlockedUser, Contact
)

chats_bp = Blueprint('chats', __name__)

@chats_bp.route('/', methods=['GET'])
@login_required
def list_conversations():
    include_archived = request.args.get('archived', 'false').lower() == 'true'
    
    db = get_db()
    try:
        # Get all conversations the user is a member of
        member_conv_ids = [
            r[0] for r in db.query(conversation_members.c.conversation_id).filter(
                conversation_members.c.user_id == current_user.id
            ).all()
        ]
        
        if not member_conv_ids:
            return jsonify({'conversations': []})
        
        conversations = db.query(Conversation).filter(
            Conversation.id.in_(member_conv_ids),
            Conversation.is_active == True
        ).order_by(Conversation.updated_at.desc()).all()
        
        result = []
        for conv in conversations:
            settings = db.query(UserChatSettings).filter(
                UserChatSettings.user_id == current_user.id,
                UserChatSettings.conversation_id == conv.id
            ).first()
            
            is_archived = settings.is_archived if settings else False
            if include_archived != is_archived and not include_archived:
                if is_archived:
                    continue
            
            # Get last message
            last_msg = db.query(Message).filter(
                Message.conversation_id == conv.id,
                Message.is_deleted_for_everyone == False
            ).order_by(Message.created_at.desc()).first()
            
            # Unread count
            last_read_id = None
            member_info = db.execute(
                conversation_members.select().where(
                    and_(
                        conversation_members.c.conversation_id == conv.id,
                        conversation_members.c.user_id == current_user.id
                    )
                )
            ).first()
            if member_info:
                last_read_id = member_info.last_read_message_id
            
            unread = 0
            if last_read_id:
                unread = db.query(func.count(Message.id)).filter(
                    Message.conversation_id == conv.id,
                    Message.id > last_read_id,
                    Message.sender_id != current_user.id,
                    Message.is_deleted_for_everyone == False
                ).scalar() or 0
            elif last_msg and last_msg.sender_id != current_user.id:
                unread = db.query(func.count(Message.id)).filter(
                    Message.conversation_id == conv.id,
                    Message.sender_id != current_user.id,
                    Message.is_deleted_for_everyone == False
                ).scalar() or 0
            
            data = conv.to_dict()
            
            # For private chats, get the other user
            if conv.type == 'private':
                other = None
                for m in conv.members:
                    if m.id != current_user.id:
                        other = m
                        break
                if other:
                    data['name'] = other.display_name
                    data['photo'] = other.profile_photo
                    data['other_user'] = other.to_dict()
                    data['is_online'] = other.is_online
            
            data['last_message'] = last_msg.to_dict(current_user.id) if last_msg else None
            data['unread_count'] = unread
            data['is_pinned'] = settings.is_pinned if settings else False
            data['is_archived'] = is_archived
            data['is_muted'] = settings.is_muted if settings else False
            
            result.append(data)
        
        # Sort: pinned first, then by updated_at
        result.sort(key=lambda x: (not x.get('is_pinned', False), x.get('updated_at') or ''), reverse=False)
        result.sort(key=lambda x: x.get('is_pinned', False), reverse=True)
        
        return jsonify({'conversations': result})
    finally:
        db.close()


@chats_bp.route('/private', methods=['POST'])
@login_required
def create_private_chat():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    db = get_db()
    try:
        other = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not other:
            return jsonify({'error': 'User not found'}), 404
        
        if other.id == current_user.id:
            return jsonify({'error': 'Cannot chat with yourself'}), 400
        
        # Check blocked
        blocked = db.query(BlockedUser).filter(
            ((BlockedUser.blocker_id == current_user.id) & (BlockedUser.blocked_id == other.id)) |
            ((BlockedUser.blocker_id == other.id) & (BlockedUser.blocked_id == current_user.id))
        ).first()
        if blocked:
            return jsonify({'error': 'Cannot start conversation'}), 403
        
        # Check if conversation already exists
        existing = db.query(Conversation).join(
            conversation_members, Conversation.id == conversation_members.c.conversation_id
        ).filter(
            Conversation.type == 'private',
            conversation_members.c.user_id == current_user.id
        ).all()
        
        for conv in existing:
            member_ids = [m.id for m in conv.members]
            if other.id in member_ids and len(member_ids) == 2:
                return jsonify({
                    'message': 'Conversation exists',
                    'conversation': conv.to_dict(),
                    'other_user': other.to_dict()
                })
        
        # Create new
        conv = Conversation(type='private', created_by=current_user.id)
        db.add(conv)
        db.flush()
        
        # Add members
        db.execute(conversation_members.insert().values(
            conversation_id=conv.id,
            user_id=current_user.id,
            role='member'
        ))
        db.execute(conversation_members.insert().values(
            conversation_id=conv.id,
            user_id=other.id,
            role='member'
        ))
        
        db.commit()
        db.refresh(conv)
        
        data = conv.to_dict()
        data['other_user'] = other.to_dict()
        data['name'] = other.display_name
        data['photo'] = other.profile_photo
        
        return jsonify({
            'message': 'Conversation created',
            'conversation': data
        }), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to create conversation', 'detail': str(e)}), 500
    finally:
        db.close()


@chats_bp.route('/<int:conv_id>', methods=['GET'])
@login_required
def get_conversation(conv_id):
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
            return jsonify({'error': 'Conversation not found'}), 404
        
        conv = db.query(Conversation).get(conv_id)
        if not conv or not conv.is_active:
            return jsonify({'error': 'Conversation not found'}), 404
        
        data = conv.to_dict()
        
        if conv.type == 'private':
            for m in conv.members:
                if m.id != current_user.id:
                    data['other_user'] = m.to_dict()
                    data['name'] = m.display_name
                    data['photo'] = m.profile_photo
                    break
        else:
            data['members'] = [m.to_dict() for m in conv.members]
        
        settings = db.query(UserChatSettings).filter(
            UserChatSettings.user_id == current_user.id,
            UserChatSettings.conversation_id == conv_id
        ).first()
        
        data['is_pinned'] = settings.is_pinned if settings else False
        data['is_archived'] = settings.is_archived if settings else False
        data['is_muted'] = settings.is_muted if settings else False
        
        return jsonify({'conversation': data})
    finally:
        db.close()


@chats_bp.route('/<int:conv_id>/settings', methods=['PUT'])
@login_required
def update_chat_settings(conv_id):
    data = request.get_json() or {}
    
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
            return jsonify({'error': 'Conversation not found'}), 404
        
        settings = db.query(UserChatSettings).filter(
            UserChatSettings.user_id == current_user.id,
            UserChatSettings.conversation_id == conv_id
        ).first()
        
        if not settings:
            settings = UserChatSettings(
                user_id=current_user.id,
                conversation_id=conv_id
            )
            db.add(settings)
        
        if 'is_pinned' in data:
            settings.is_pinned = bool(data['is_pinned'])
        if 'is_archived' in data:
            settings.is_archived = bool(data['is_archived'])
        if 'is_muted' in data:
            settings.is_muted = bool(data['is_muted'])
        if 'is_unread' in data:
            settings.is_unread = bool(data['is_unread'])
        
        settings.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({
            'message': 'Settings updated',
            'settings': {
                'is_pinned': settings.is_pinned,
                'is_archived': settings.is_archived,
                'is_muted': settings.is_muted,
                'is_unread': settings.is_unread,
            }
        })
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to update settings'}), 500
    finally:
        db.close()


@chats_bp.route('/<int:conv_id>/read', methods=['POST'])
@login_required
def mark_as_read(conv_id):
    data = request.get_json() or {}
    message_id = data.get('message_id')
    
    db = get_db()
    try:
        if message_id:
            # Update last_read_message_id
            db.execute(
                conversation_members.update().where(
                    and_(
                        conversation_members.c.conversation_id == conv_id,
                        conversation_members.c.user_id == current_user.id
                    )
                ).values(last_read_message_id=message_id)
            )
        
        settings = db.query(UserChatSettings).filter(
            UserChatSettings.user_id == current_user.id,
            UserChatSettings.conversation_id == conv_id
        ).first()
        if settings:
            settings.is_unread = False
        
        db.commit()
        return jsonify({'message': 'Marked as read'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@chats_bp.route('/<int:conv_id>', methods=['DELETE'])
@login_required
def delete_chat(conv_id):
    """Delete chat for current user (hide messages)"""
    db = get_db()
    try:
        # For private: just leave / archive
        # For now, mark as archived and clear
        settings = db.query(UserChatSettings).filter(
            UserChatSettings.user_id == current_user.id,
            UserChatSettings.conversation_id == conv_id
        ).first()
        
        if not settings:
            settings = UserChatSettings(
                user_id=current_user.id,
                conversation_id=conv_id,
                is_archived=True
            )
            db.add(settings)
        else:
            settings.is_archived = True
        
        db.commit()
        return jsonify({'message': 'Chat deleted'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to delete chat'}), 500
    finally:
        db.close()


@chats_bp.route('/search', methods=['GET'])
@login_required
def search_chats():
    query = (request.args.get('q') or '').strip()
    if len(query) < 1:
        return jsonify({'conversations': [], 'messages': [], 'users': []})
    
    db = get_db()
    try:
        # Search conversations by name
        member_conv_ids = [r[0] for r in db.query(conversation_members.c.conversation_id).filter(
            conversation_members.c.user_id == current_user.id
        ).all()]
        
        convs = db.query(Conversation).filter(
            Conversation.id.in_(member_conv_ids),
            Conversation.is_active == True,
            Conversation.name.ilike(f'%{query}%')
        ).limit(10).all()
        
        # Search users
        users = db.query(User).filter(
            User.is_active == True,
            User.id != current_user.id,
            (User.username.ilike(f'%{query}%')) | (User.display_name.ilike(f'%{query}%'))
        ).limit(10).all()
        
        # Search messages
        messages = db.query(Message).filter(
            Message.conversation_id.in_(member_conv_ids),
            Message.is_deleted_for_everyone == False,
            Message.content.ilike(f'%{query}%')
        ).order_by(Message.created_at.desc()).limit(20).all()
        
        return jsonify({
            'conversations': [c.to_dict() for c in convs],
            'users': [u.to_dict() for u in users],
            'messages': [m.to_dict(current_user.id) for m in messages if m.to_dict(current_user.id)]
        })
    finally:
        db.close()
