from flask import Blueprint, request, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone, timedelta
import re
import secrets

from database.database import get_db
from database.models import User, Session as UserSession, PasswordResetToken, Device

auth_bp = Blueprint('auth', __name__)

def validate_email(email):
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None

def validate_username(username):
    if not username or len(username) < 3 or len(username) > 30:
        return False
    return re.match(r'^[a-zA-Z0-9_]+$', username) is not None

def validate_password(password):
    if not password or len(password) < 8:
        return False, 'Password must be at least 8 characters'
    if not re.search(r'[A-Za-z]', password):
        return False, 'Password must contain at least one letter'
    if not re.search(r'[0-9]', password):
        return False, 'Password must contain at least one number'
    return True, None

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    
    username = (data.get('username') or '').strip().lower()
    email = (data.get('email') or '').strip().lower()
    password = data.get('password') or ''
    display_name = (data.get('display_name') or '').strip()
    
    errors = {}
    
    if not validate_username(username):
        errors['username'] = 'Username must be 3-30 characters, letters, numbers, and underscores only'
    
    if not validate_email(email):
        errors['email'] = 'Invalid email address'
    
    valid_pw, pw_error = validate_password(password)
    if not valid_pw:
        errors['password'] = pw_error
    
    if not display_name or len(display_name) < 1 or len(display_name) > 100:
        errors['display_name'] = 'Display name is required (1-100 characters)'
    
    if errors:
        return jsonify({'error': 'Validation failed', 'errors': errors}), 400
    
    db = get_db()
    try:
        if db.query(User).filter(User.username == username).first():
            return jsonify({'error': 'Username already taken'}), 409
        
        if db.query(User).filter(User.email == email).first():
            return jsonify({'error': 'Email already registered'}), 409
        
        user = User(
            username=username,
            email=email,
            display_name=display_name,
            bio='',
        )
        user.set_password(password)
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        login_user(user, remember=True)
        
        # Create session record
        sess = UserSession(
            user_id=user.id,
            session_token=UserSession.generate_token(),
            device_info=request.headers.get('User-Agent', '')[:500],
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(sess)
        db.commit()
        
        return jsonify({
            'message': 'Registration successful',
            'user': user.to_dict(include_private=True)
        }), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Registration failed', 'detail': str(e)}), 500
    finally:
        db.close()


@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    
    identifier = (data.get('identifier') or data.get('email') or data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    remember = data.get('remember', True)
    
    if not identifier or not password:
        return jsonify({'error': 'Email/username and password are required'}), 400
    
    db = get_db()
    try:
        user = db.query(User).filter(
            (User.email == identifier) | (User.username == identifier)
        ).first()
        
        if not user or not user.check_password(password):
            return jsonify({'error': 'Invalid credentials'}), 401
        
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated'}), 403
        
        login_user(user, remember=remember)
        
        user.is_online = True
        user.last_seen = datetime.now(timezone.utc)
        
        # Create session
        sess = UserSession(
            user_id=user.id,
            session_token=UserSession.generate_token(),
            device_info=request.headers.get('User-Agent', '')[:500],
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:500],
            expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        )
        db.add(sess)
        db.commit()
        
        return jsonify({
            'message': 'Login successful',
            'user': user.to_dict(include_private=True),
            'session_token': sess.session_token
        })
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Login failed', 'detail': str(e)}), 500
    finally:
        db.close()


@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    db = get_db()
    try:
        user = db.query(User).get(current_user.id)
        if user:
            user.is_online = False
            user.last_seen = datetime.now(timezone.utc)
            db.commit()
        logout_user()
        return jsonify({'message': 'Logged out successfully'})
    except Exception:
        db.rollback()
        logout_user()
        return jsonify({'message': 'Logged out'})
    finally:
        db.close()


@auth_bp.route('/me', methods=['GET'])
@login_required
def me():
    return jsonify({'user': current_user.to_dict(include_private=True)})


@auth_bp.route('/forgot-password', methods=['POST'])
def forgot_password():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip().lower()
    
    if not validate_email(email):
        return jsonify({'error': 'Invalid email address'}), 400
    
    db = get_db()
    try:
        user = db.query(User).filter(User.email == email).first()
        
        # Always return success to prevent email enumeration
        if user:
            # Invalidate old tokens
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used == False
            ).update({'used': True})
            
            token = PasswordResetToken(
                user_id=user.id,
                token=PasswordResetToken.generate_token(),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)
            )
            db.add(token)
            db.commit()
            
            # In production, send email with reset link
            # For development, return token (remove in production)
            return jsonify({
                'message': 'If an account exists with this email, a reset link has been sent.',
                'dev_token': token.token  # Remove in production
            })
        
        return jsonify({'message': 'If an account exists with this email, a reset link has been sent.'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Request failed'}), 500
    finally:
        db.close()


@auth_bp.route('/reset-password', methods=['POST'])
def reset_password():
    data = request.get_json() or {}
    token = data.get('token') or ''
    password = data.get('password') or ''
    
    valid_pw, pw_error = validate_password(password)
    if not valid_pw:
        return jsonify({'error': pw_error}), 400
    
    db = get_db()
    try:
        reset_token = db.query(PasswordResetToken).filter(
            PasswordResetToken.token == token,
            PasswordResetToken.used == False,
            PasswordResetToken.expires_at > datetime.now(timezone.utc)
        ).first()
        
        if not reset_token:
            return jsonify({'error': 'Invalid or expired reset token'}), 400
        
        user = db.query(User).get(reset_token.user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        user.set_password(password)
        reset_token.used = True
        db.commit()
        
        return jsonify({'message': 'Password reset successful'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Reset failed'}), 500
    finally:
        db.close()


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json() or {}
    current_password = data.get('current_password') or ''
    new_password = data.get('new_password') or ''
    
    valid_pw, pw_error = validate_password(new_password)
    if not valid_pw:
        return jsonify({'error': pw_error}), 400
    
    db = get_db()
    try:
        user = db.query(User).get(current_user.id)
        if not user.check_password(current_password):
            return jsonify({'error': 'Current password is incorrect'}), 401
        
        user.set_password(new_password)
        db.commit()
        
        return jsonify({'message': 'Password changed successfully'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to change password'}), 500
    finally:
        db.close()


@auth_bp.route('/sessions', methods=['GET'])
@login_required
def list_sessions():
    db = get_db()
    try:
        sessions = db.query(UserSession).filter(
            UserSession.user_id == current_user.id,
            UserSession.is_active == True
        ).order_by(UserSession.last_active.desc()).all()
        
        return jsonify({
            'sessions': [{
                'id': s.id,
                'device_info': s.device_info,
                'ip_address': s.ip_address,
                'created_at': s.created_at.isoformat() if s.created_at else None,
                'last_active': s.last_active.isoformat() if s.last_active else None,
            } for s in sessions]
        })
    finally:
        db.close()


@auth_bp.route('/sessions/<int:session_id>', methods=['DELETE'])
@login_required
def revoke_session(session_id):
    db = get_db()
    try:
        sess = db.query(UserSession).filter(
            UserSession.id == session_id,
            UserSession.user_id == current_user.id
        ).first()
        
        if not sess:
            return jsonify({'error': 'Session not found'}), 404
        
        sess.is_active = False
        db.commit()
        
        return jsonify({'message': 'Session revoked'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to revoke session'}), 500
    finally:
        db.close()


@auth_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    data = request.get_json() or {}
    password = data.get('password') or ''
    
    db = get_db()
    try:
        user = db.query(User).get(current_user.id)
        if not user.check_password(password):
            return jsonify({'error': 'Password is incorrect'}), 401
        
        user.is_active = False
        user.email = f'deleted_{user.id}_{user.email}'
        user.username = f'deleted_{user.id}_{user.username}'
        db.commit()
        
        logout_user()
        return jsonify({'message': 'Account deleted successfully'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed to delete account'}), 500
    finally:
        db.close()
