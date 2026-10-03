from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
import os
import uuid

from database.database import get_db
from database.models import User, Contact, BlockedUser, Report

users_bp = Blueprint('users', __name__)

@users_bp.route('/search', methods=['GET'])
@login_required
def search_users():
    query = (request.args.get('q') or '').strip()
    limit = min(int(request.args.get('limit', 20)), 50)
    
    if len(query) < 2:
        return jsonify({'users': []})
    
    db = get_db()
    try:
        # Get blocked users
        blocked_ids = [b.blocked_id for b in db.query(BlockedUser).filter(
            BlockedUser.blocker_id == current_user.id
        ).all()]
        blocked_by_ids = [b.blocker_id for b in db.query(BlockedUser).filter(
            BlockedUser.blocked_id == current_user.id
        ).all()]
        exclude_ids = set(blocked_ids + blocked_by_ids + [current_user.id])
        
        users = db.query(User).filter(
            User.is_active == True,
            ~User.id.in_(exclude_ids) if exclude_ids else True,
            (User.username.ilike(f'%{query}%')) | (User.display_name.ilike(f'%{query}%'))
        ).limit(limit).all()
        
        return jsonify({
            'users': [u.to_dict() for u in users]
        })
    finally:
        db.close()


@users_bp.route('/profile/<username>', methods=['GET'])
@login_required
def get_profile(username):
    db = get_db()
    try:
        user = db.query(User).filter(
            User.username == username.lower(),
            User.is_active == True
        ).first()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Check if blocked
        blocked = db.query(BlockedUser).filter(
            ((BlockedUser.blocker_id == current_user.id) & (BlockedUser.blocked_id == user.id)) |
            ((BlockedUser.blocker_id == user.id) & (BlockedUser.blocked_id == current_user.id))
        ).first()
        
        if blocked:
            return jsonify({'error': 'User not found'}), 404
        
        data = user.to_dict()
        
        # Check if contact
        is_contact = db.query(Contact).filter(
            Contact.user_id == current_user.id,
            Contact.contact_id == user.id
        ).first() is not None
        data['is_contact'] = is_contact
        
        return jsonify({'user': data})
    finally:
        db.close()


@users_bp.route('/profile', methods=['PUT'])
@login_required
def update_profile():
    data = request.get_json() or {}
    
    db = get_db()
    try:
        user = db.query(User).get(current_user.id)
        
        if 'display_name' in data:
            name = (data['display_name'] or '').strip()
            if not name or len(name) > 100:
                return jsonify({'error': 'Display name must be 1-100 characters'}), 400
            user.display_name = name
        
        if 'bio' in data:
            bio = (data['bio'] or '')[:500]
            user.bio = bio
        
        if 'username' in data:
            new_username = (data['username'] or '').strip().lower()
            if new_username != user.username:
                import re
                if not re.match(r'^[a-zA-Z0-9_]{3,30}$', new_username):
                    return jsonify({'error': 'Invalid username format'}), 400
                existing = db.query(User).filter(User.username == new_username).first()
                if existing:
                    return jsonify({'error': 'Username already taken'}), 409
                user.username = new_username
        
        # Privacy settings
        for field in ['show_last_seen', 'show_online_status', 'profile_visibility']:
            if field in data and data[field] in ('everyone', 'contacts', 'nobody'):
                setattr(user, field, data[field])
        
        for field in ['show_read_receipts', 'show_typing_indicator']:
            if field in data:
                setattr(user, field, bool(data[field]))
        
        # Notification settings
        for field in ['notify_messages', 'notify_groups', 'notify_calls', 'notify_preview', 'notify_sound']:
            if field in data:
                setattr(user, field, bool(data[field]))
        
        # Theme
        if 'theme' in data and data['theme'] in ('light', 'dark', 'system'):
            user.theme = data['theme']
        
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({
            'message': 'Profile updated',
            'user': user.to_dict(include_private=True)
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to update profile', 'detail': str(e)}), 500
    finally:
        db.close()


@users_bp.route('/profile/photo', methods=['POST'])
@login_required
def upload_profile_photo():
    if 'photo' not in request.files:
        return jsonify({'error': 'No photo provided'}), 400
    
    file = request.files['photo']
    if not file or not file.filename:
        return jsonify({'error': 'No photo provided'}), 400
    
    # Validate
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed:
        return jsonify({'error': 'Invalid file type. Allowed: png, jpg, jpeg, gif, webp'}), 400
    
    # Check size (max 5MB)
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size > 5 * 1024 * 1024:
        return jsonify({'error': 'File too large. Maximum 5MB'}), 400
    
    db = get_db()
    try:
        filename = f'profile_{current_user.id}_{uuid.uuid4().hex[:12]}.{ext}'
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)
        
        # Try to create thumbnail with Pillow
        try:
            from PIL import Image
            img = Image.open(filepath)
            img.thumbnail((400, 400))
            img.save(filepath, optimize=True, quality=85)
        except Exception:
            pass
        
        user = db.query(User).get(current_user.id)
        
        # Delete old photo
        if user.profile_photo:
            old_path = os.path.join(upload_folder, user.profile_photo)
            if os.path.exists(old_path):
                try:
                    os.remove(old_path)
                except Exception:
                    pass
        
        user.profile_photo = filename
        user.updated_at = datetime.now(timezone.utc)
        db.commit()
        
        return jsonify({
            'message': 'Profile photo updated',
            'profile_photo': filename,
            'url': f'/uploads/{filename}'
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to upload photo', 'detail': str(e)}), 500
    finally:
        db.close()


@users_bp.route('/contacts', methods=['GET'])
@login_required
def list_contacts():
    db = get_db()
    try:
        contacts = db.query(Contact).filter(Contact.user_id == current_user.id).all()
        result = []
        for c in contacts:
            if c.contact_user and c.contact_user.is_active:
                data = c.contact_user.to_dict()
                data['nickname'] = c.nickname
                data['contact_id'] = c.id
                result.append(data)
        return jsonify({'contacts': result})
    finally:
        db.close()


@users_bp.route('/contacts', methods=['POST'])
@login_required
def add_contact():
    data = request.get_json() or {}
    contact_user_id = data.get('user_id')
    username = data.get('username')
    
    db = get_db()
    try:
        if contact_user_id:
            contact_user = db.query(User).filter(User.id == contact_user_id, User.is_active == True).first()
        elif username:
            contact_user = db.query(User).filter(User.username == username.lower(), User.is_active == True).first()
        else:
            return jsonify({'error': 'user_id or username required'}), 400
        
        if not contact_user:
            return jsonify({'error': 'User not found'}), 404
        
        if contact_user.id == current_user.id:
            return jsonify({'error': 'Cannot add yourself'}), 400
        
        existing = db.query(Contact).filter(
            Contact.user_id == current_user.id,
            Contact.contact_id == contact_user.id
        ).first()
        
        if existing:
            return jsonify({'error': 'Already in contacts', 'contact': contact_user.to_dict()}), 409
        
        contact = Contact(
            user_id=current_user.id,
            contact_id=contact_user.id,
            nickname=data.get('nickname')
        )
        db.add(contact)
        db.commit()
        
        return jsonify({
            'message': 'Contact added',
            'contact': contact_user.to_dict()
        }), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to add contact'}), 500
    finally:
        db.close()


@users_bp.route('/contacts/<int:contact_id>', methods=['DELETE'])
@login_required
def remove_contact(contact_id):
    db = get_db()
    try:
        contact = db.query(Contact).filter(
            Contact.id == contact_id,
            Contact.user_id == current_user.id
        ).first()
        
        if not contact:
            # Try by user id
            contact = db.query(Contact).filter(
                Contact.contact_id == contact_id,
                Contact.user_id == current_user.id
            ).first()
        
        if not contact:
            return jsonify({'error': 'Contact not found'}), 404
        
        db.delete(contact)
        db.commit()
        return jsonify({'message': 'Contact removed'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to remove contact'}), 500
    finally:
        db.close()


@users_bp.route('/block', methods=['POST'])
@login_required
def block_user():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    
    db = get_db()
    try:
        target = db.query(User).get(user_id)
        if not target or not target.is_active:
            return jsonify({'error': 'User not found'}), 404
        
        if target.id == current_user.id:
            return jsonify({'error': 'Cannot block yourself'}), 400
        
        existing = db.query(BlockedUser).filter(
            BlockedUser.blocker_id == current_user.id,
            BlockedUser.blocked_id == target.id
        ).first()
        
        if existing:
            return jsonify({'message': 'User already blocked'})
        
        block = BlockedUser(
            blocker_id=current_user.id,
            blocked_id=target.id,
            reason=data.get('reason')
        )
        db.add(block)
        
        # Remove from contacts
        db.query(Contact).filter(
            ((Contact.user_id == current_user.id) & (Contact.contact_id == target.id)) |
            ((Contact.user_id == target.id) & (Contact.contact_id == current_user.id))
        ).delete(synchronize_session=False)
        
        db.commit()
        return jsonify({'message': 'User blocked'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to block user'}), 500
    finally:
        db.close()


@users_bp.route('/unblock', methods=['POST'])
@login_required
def unblock_user():
    data = request.get_json() or {}
    user_id = data.get('user_id')
    
    db = get_db()
    try:
        block = db.query(BlockedUser).filter(
            BlockedUser.blocker_id == current_user.id,
            BlockedUser.blocked_id == user_id
        ).first()
        
        if not block:
            return jsonify({'error': 'User not blocked'}), 404
        
        db.delete(block)
        db.commit()
        return jsonify({'message': 'User unblocked'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to unblock'}), 500
    finally:
        db.close()


@users_bp.route('/blocked', methods=['GET'])
@login_required
def list_blocked():
    db = get_db()
    try:
        blocks = db.query(BlockedUser).filter(BlockedUser.blocker_id == current_user.id).all()
        result = []
        for b in blocks:
            if b.blocked_user:
                data = b.blocked_user.to_dict()
                data['blocked_at'] = b.created_at.isoformat() if b.created_at else None
                result.append(data)
        return jsonify({'blocked': result})
    finally:
        db.close()


@users_bp.route('/report', methods=['POST'])
@login_required
def report():
    data = request.get_json() or {}
    report_type = data.get('type')  # user, message, group
    reason = (data.get('reason') or '').strip()
    
    if report_type not in ('user', 'message', 'group'):
        return jsonify({'error': 'Invalid report type'}), 400
    
    if not reason:
        return jsonify({'error': 'Reason is required'}), 400
    
    db = get_db()
    try:
        report = Report(
            reporter_id=current_user.id,
            report_type=report_type,
            reported_user_id=data.get('user_id'),
            reported_message_id=data.get('message_id'),
            reported_conversation_id=data.get('conversation_id'),
            reason=reason,
            details=data.get('details')
        )
        db.add(report)
        db.commit()
        return jsonify({'message': 'Report submitted'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to submit report'}), 500
    finally:
        db.close()
