from flask import Blueprint, request, jsonify, current_app, send_from_directory
from flask_login import login_required, current_user
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
from sqlalchemy import and_
import os
import uuid
import mimetypes

from database.database import get_db
from database.models import Message, Attachment, Conversation, conversation_members

files_bp = Blueprint('files', __name__)

def get_file_type(ext, mime):
    ext = ext.lower()
    if ext in current_app.config['ALLOWED_EXTENSIONS']['image'] or (mime and mime.startswith('image/')):
        return 'image'
    if ext in current_app.config['ALLOWED_EXTENSIONS']['video'] or (mime and mime.startswith('video/')):
        return 'video'
    if ext in current_app.config['ALLOWED_EXTENSIONS']['audio'] or (mime and mime.startswith('audio/')):
        return 'audio'
    if ext in current_app.config['ALLOWED_EXTENSIONS']['document']:
        return 'document'
    if ext in current_app.config['ALLOWED_EXTENSIONS']['archive']:
        return 'archive'
    return 'other'

def allowed_file(filename):
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    all_ext = set()
    for v in current_app.config['ALLOWED_EXTENSIONS'].values():
        all_ext.update(v)
    return ext in all_ext

@files_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    conv_id = request.form.get('conversation_id', type=int)
    content = request.form.get('content', '').strip()
    reply_to_id = request.form.get('reply_to_id', type=int)
    
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400
    
    if not conv_id:
        return jsonify({'error': 'conversation_id required'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': 'File type not allowed'}), 400
    
    # Check size
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    
    max_size = current_app.config['MAX_CONTENT_LENGTH']
    if size > max_size:
        return jsonify({'error': f'File too large. Maximum {max_size // (1024*1024)}MB'}), 400
    
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
        
        original_filename = secure_filename(file.filename)
        ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
        unique_name = f'{uuid.uuid4().hex}_{original_filename}'
        
        upload_folder = current_app.config['UPLOAD_FOLDER']
        os.makedirs(upload_folder, exist_ok=True)
        filepath = os.path.join(upload_folder, unique_name)
        file.save(filepath)
        
        mime_type = mimetypes.guess_type(original_filename)[0] or file.content_type or 'application/octet-stream'
        file_type = get_file_type(ext, mime_type)
        
        # Determine message type
        msg_type = file_type if file_type in ('image', 'video', 'audio') else 'document'
        
        # Create message
        msg = Message(
            conversation_id=conv_id,
            sender_id=current_user.id,
            content=content if content else None,
            message_type=msg_type,
            reply_to_id=reply_to_id,
            status='sent'
        )
        db.add(msg)
        db.flush()
        
        # Thumbnail for images
        thumbnail_path = None
        width = height = duration = None
        
        if file_type == 'image':
            try:
                from PIL import Image
                img = Image.open(filepath)
                width, height = img.size
                # Create thumbnail
                thumb_name = f'thumb_{unique_name}'
                thumb_path = os.path.join(upload_folder, thumb_name)
                img.thumbnail((400, 400))
                img.save(thumb_path, optimize=True, quality=80)
                thumbnail_path = thumb_name
            except Exception:
                pass
        
        att = Attachment(
            message_id=msg.id,
            filename=unique_name,
            original_filename=original_filename,
            file_path=filepath,
            file_type=file_type,
            mime_type=mime_type,
            file_size=size,
            duration=duration,
            width=width,
            height=height,
            thumbnail_path=thumbnail_path,
        )
        db.add(att)
        
        conv = db.query(Conversation).get(conv_id)
        if conv:
            conv.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(msg)
        
        result = msg.to_dict(current_user.id)
        
        try:
            from app import socketio
            socketio.emit('new_message', result, room=f'conversation_{conv_id}')
        except Exception:
            pass
        
        return jsonify({'message': result}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Upload failed', 'detail': str(e)}), 500
    finally:
        db.close()


@files_bp.route('/upload/voice', methods=['POST'])
@login_required
def upload_voice():
    if 'audio' not in request.files:
        return jsonify({'error': 'No audio provided'}), 400
    
    file = request.files['audio']
    conv_id = request.form.get('conversation_id', type=int)
    duration = request.form.get('duration', type=float)
    
    if not conv_id:
        return jsonify({'error': 'conversation_id required'}), 400
    
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
            return jsonify({'error': 'Not a member'}), 403
        
        original_filename = secure_filename(file.filename or 'voice.webm')
        ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else 'webm'
        unique_name = f'voice_{uuid.uuid4().hex}.{ext}'
        
        upload_folder = current_app.config['UPLOAD_FOLDER']
        filepath = os.path.join(upload_folder, unique_name)
        file.save(filepath)
        
        size = os.path.getsize(filepath)
        
        msg = Message(
            conversation_id=conv_id,
            sender_id=current_user.id,
            message_type='audio',
            status='sent'
        )
        db.add(msg)
        db.flush()
        
        att = Attachment(
            message_id=msg.id,
            filename=unique_name,
            original_filename=original_filename,
            file_path=filepath,
            file_type='audio',
            mime_type=file.content_type or 'audio/webm',
            file_size=size,
            duration=duration,
        )
        db.add(att)
        
        conv = db.query(Conversation).get(conv_id)
        if conv:
            conv.updated_at = datetime.now(timezone.utc)
        
        db.commit()
        db.refresh(msg)
        
        result = msg.to_dict(current_user.id)
        
        try:
            from app import socketio
            socketio.emit('new_message', result, room=f'conversation_{conv_id}')
        except Exception:
            pass
        
        return jsonify({'message': result}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Upload failed', 'detail': str(e)}), 500
    finally:
        db.close()


@files_bp.route('/media/<int:conv_id>', methods=['GET'])
@login_required
def get_media(conv_id):
    media_type = request.args.get('type', 'all')  # image, video, audio, document, all
    
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
        
        query = db.query(Attachment).join(Message).filter(
            Message.conversation_id == conv_id,
            Message.is_deleted_for_everyone == False
        )
        
        if media_type != 'all':
            query = query.filter(Attachment.file_type == media_type)
        
        attachments = query.order_by(Attachment.created_at.desc()).limit(100).all()
        
        return jsonify({
            'media': [a.to_dict() for a in attachments]
        })
    finally:
        db.close()
