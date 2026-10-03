from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
from sqlalchemy import and_
from werkzeug.utils import secure_filename
import os
import uuid
import secrets

from database.database import get_db
from database.models import (
    Conversation, User, Message, conversation_members, Attachment
)

groups_bp = Blueprint('groups', __name__)

@groups_bp.route('/', methods=['POST'])
@login_required
def create_group():
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    member_ids = data.get('member_ids') or []
    
    if not name or len(name) > 200:
        return jsonify({'error': 'Group name required (max 200 characters)'}), 400
    
    db = get_db()
    try:
        conv = Conversation(
            type='group',
            name=name,
            description=description,
            created_by=current_user.id,
        )
        conv.generate_invite_link()
        db.add(conv)
        db.flush()
        
        # Add creator as owner
        db.execute(conversation_members.insert().values(
            conversation_id=conv.id,
            user_id=current_user.id,
            role='owner'
        ))
        
        # Add members
        for mid in member_ids:
            if mid == current_user.id:
                continue
            user = db.query(User).filter(User.id == mid, User.is_active == True).first()
            if user:
                db.execute(conversation_members.insert().values(
                    conversation_id=conv.id,
                    user_id=user.id,
                    role='member'
                ))
        
        # System message
        sys_msg = Message(
            conversation_id=conv.id,
            sender_id=None,
            content=f'{current_user.display_name} created the group',
            message_type='system',
            status='sent'
        )
        db.add(sys_msg)
        
        db.commit()
        db.refresh(conv)
        
        data = conv.to_dict()
        data['members'] = [m.to_dict() for m in conv.members]
        data['role'] = 'owner'
        
        return jsonify({'message': 'Group created', 'conversation': data}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to create group', 'detail': str(e)}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>', methods=['GET'])
@login_required
def get_group(group_id):
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        if not member:
            return jsonify({'error': 'Group not found'}), 404
        
        conv = db.query(Conversation).filter(
            Conversation.id == group_id,
            Conversation.type == 'group',
            Conversation.is_active == True
        ).first()
        
        if not conv:
            return jsonify({'error': 'Group not found'}), 404
        
        data = conv.to_dict()
        data['members'] = []
        for m in conv.members:
            md = m.to_dict()
            # Get role
            m_info = db.execute(
                conversation_members.select().where(
                    and_(
                        conversation_members.c.conversation_id == group_id,
                        conversation_members.c.user_id == m.id
                    )
                )
            ).first()
            md['role'] = m_info.role if m_info else 'member'
            data['members'].append(md)
        
        data['role'] = member.role
        data['invite_link'] = conv.invite_link
        
        # Media, files, links, pinned
        messages = db.query(Message).filter(
            Message.conversation_id == group_id,
            Message.is_deleted_for_everyone == False
        ).all()
        
        media = []
        files = []
        links = []
        pinned = []
        
        for msg in messages:
            if msg.is_pinned:
                d = msg.to_dict(current_user.id)
                if d:
                    pinned.append(d)
            for att in msg.attachments:
                if att.file_type in ('image', 'video'):
                    media.append(att.to_dict())
                else:
                    files.append(att.to_dict())
            if msg.content and ('http://' in msg.content or 'https://' in msg.content):
                links.append({
                    'message_id': msg.id,
                    'content': msg.content,
                    'created_at': msg.created_at.isoformat() if msg.created_at else None
                })
        
        data['media'] = media[:50]
        data['files'] = files[:50]
        data['links'] = links[:50]
        data['pinned_messages'] = pinned
        
        return jsonify({'group': data})
    finally:
        db.close()


@groups_bp.route('/<int:group_id>', methods=['PUT'])
@login_required
def update_group(group_id):
    data = request.get_json() or {}
    
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member or member.role not in ('admin', 'owner'):
            return jsonify({'error': 'Only admins can update group'}), 403
        
        conv = db.query(Conversation).get(group_id)
        if not conv or conv.type != 'group':
            return jsonify({'error': 'Group not found'}), 404
        
        if 'name' in data:
            name = (data['name'] or '').strip()
            if name and len(name) <= 200:
                conv.name = name
        
        if 'description' in data:
            conv.description = (data['description'] or '')[:1000]
        
        if 'only_admins_can_post' in data:
            conv.only_admins_can_post = bool(data['only_admins_can_post'])
        
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({'message': 'Group updated', 'conversation': conv.to_dict()})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to update group'}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>/photo', methods=['POST'])
@login_required
def update_group_photo(group_id):
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo provided'}), 400
    
    file = request.files['photo']
    if not file or not file.filename:
        return jsonify({'error': 'No photo provided'}), 400
    
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        return jsonify({'error': 'Invalid file type'}), 400
    
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member or member.role not in ('admin', 'owner'):
            return jsonify({'error': 'Only admins can update group photo'}), 403
        
        conv = db.query(Conversation).get(group_id)
        if not conv:
            return jsonify({'error': 'Group not found'}), 404
        
        filename = f'group_{group_id}_{uuid.uuid4().hex[:12]}.{ext}'
        upload_folder = current_app.config['UPLOAD_FOLDER']
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        try:
            from PIL import Image
            img = Image.open(filepath)
            img.thumbnail((400, 400))
            img.save(filepath, optimize=True, quality=85)
        except Exception:
            pass
        
        if conv.photo:
            old = os.path.join(upload_folder, conv.photo)
            if os.path.exists(old):
                try:
                    os.remove(old)
                except Exception:
                    pass
        
        conv.photo = filename
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({
            'message': 'Group photo updated',
            'photo': filename,
            'url': f'/uploads/{filename}'
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed', 'detail': str(e)}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>/members', methods=['POST'])
@login_required
def add_members(group_id):
    data = request.get_json() or {}
    member_ids = data.get('member_ids') or []
    
    if not member_ids:
        return jsonify({'error': 'member_ids required'}), 400
    
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member or member.role not in ('admin', 'owner'):
            return jsonify({'error': 'Only admins can add members'}), 403
        
        conv = db.query(Conversation).get(group_id)
        if not conv:
            return jsonify({'error': 'Group not found'}), 404
        
        added = []
        for mid in member_ids:
            user = db.query(User).filter(User.id == mid, User.is_active == True).first()
            if not user:
                continue
            
            existing = db.execute(
                conversation_members.select().where(
                    and_(
                        conversation_members.c.conversation_id == group_id,
                        conversation_members.c.user_id == mid
                    )
                )
            ).first()
            
            if not existing:
                db.execute(conversation_members.insert().values(
                    conversation_id=group_id,
                    user_id=mid,
                    role='member'
                ))
                added.append(user.to_dict())
                
                # System message
                sys_msg = Message(
                    conversation_id=group_id,
                    sender_id=None,
                    content=f'{current_user.display_name} added {user.display_name}',
                    message_type='system',
                    status='sent'
                )
                db.add(sys_msg)
        
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({'message': f'Added {len(added)} members', 'added': added})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed', 'detail': str(e)}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>/members/<int:user_id>', methods=['DELETE'])
@login_required
def remove_member(group_id, user_id):
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member:
            return jsonify({'error': 'Not a member'}), 403
        
        # Can remove self (leave) or admin can remove others
        if user_id != current_user.id and member.role not in ('admin', 'owner'):
            return jsonify({'error': 'Only admins can remove members'}), 403
        
        target = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == user_id
                )
            )
        ).first()
        
        if not target:
            return jsonify({'error': 'User not in group'}), 404
        
        # Cannot remove owner
        if target.role == 'owner' and user_id != current_user.id:
            return jsonify({'error': 'Cannot remove group owner'}), 403
        
        db.execute(
            conversation_members.delete().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == user_id
                )
            )
        )
        
        target_user = db.query(User).get(user_id)
        name = target_user.display_name if target_user else 'User'
        
        if user_id == current_user.id:
            content = f'{current_user.display_name} left the group'
        else:
            content = f'{current_user.display_name} removed {name}'
        
        sys_msg = Message(
            conversation_id=group_id,
            sender_id=None,
            content=content,
            message_type='system',
            status='sent'
        )
        db.add(sys_msg)
        
        db.commit()
        return jsonify({'message': 'Member removed'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>/admins/<int:user_id>', methods=['POST'])
@login_required
def make_admin(group_id, user_id):
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member or member.role != 'owner':
            return jsonify({'error': 'Only owner can manage admins'}), 403
        
        db.execute(
            conversation_members.update().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == user_id
                )
            ).values(role='admin')
        )
        db.commit()
        return jsonify({'message': 'User promoted to admin'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>/admins/<int:user_id>', methods=['DELETE'])
@login_required
def remove_admin(group_id, user_id):
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member or member.role != 'owner':
            return jsonify({'error': 'Only owner can manage admins'}), 403
        
        db.execute(
            conversation_members.update().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == user_id
                )
            ).values(role='member')
        )
        db.commit()
        return jsonify({'message': 'Admin privileges removed'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@groups_bp.route('/join/<invite_code>', methods=['POST'])
@login_required
def join_via_invite(invite_code):
    db = get_db()
    try:
        conv = db.query(Conversation).filter(
            Conversation.invite_link == invite_code,
            Conversation.type == 'group',
            Conversation.is_active == True
        ).first()
        
        if not conv:
            return jsonify({'error': 'Invalid invite link'}), 404
        
        existing = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == conv.id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if existing:
            return jsonify({'message': 'Already a member', 'conversation': conv.to_dict()})
        
        db.execute(conversation_members.insert().values(
            conversation_id=conv.id,
            user_id=current_user.id,
            role='member'
        ))
        
        sys_msg = Message(
            conversation_id=conv.id,
            sender_id=None,
            content=f'{current_user.display_name} joined the group',
            message_type='system',
            status='sent'
        )
        db.add(sys_msg)
        conv.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({'message': 'Joined group', 'conversation': conv.to_dict()}), 201
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to join'}), 500
    finally:
        db.close()


@groups_bp.route('/<int:group_id>/invite', methods=['POST'])
@login_required
def regenerate_invite(group_id):
    db = get_db()
    try:
        member = db.execute(
            conversation_members.select().where(
                and_(
                    conversation_members.c.conversation_id == group_id,
                    conversation_members.c.user_id == current_user.id
                )
            )
        ).first()
        
        if not member or member.role not in ('admin', 'owner'):
            return jsonify({'error': 'Only admins can manage invite links'}), 403
        
        conv = db.query(Conversation).get(group_id)
        if not conv:
            return jsonify({'error': 'Group not found'}), 404
        
        link = conv.generate_invite_link()
        db.commit()
        
        return jsonify({'invite_link': link})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()
