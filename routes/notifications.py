from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
import json

from database.database import get_db
from database.models import PushSubscription, User

notifications_bp = Blueprint('notifications', __name__)

@notifications_bp.route('/vapid-public-key', methods=['GET'])
def vapid_public_key():
    key = current_app.config.get('VAPID_PUBLIC_KEY')
    if not key:
        return jsonify({'error': 'Push notifications not configured'}), 503
    return jsonify({'publicKey': key})


@notifications_bp.route('/subscribe', methods=['POST'])
@login_required
def subscribe():
    data = request.get_json() or {}
    subscription = data.get('subscription')
    
    if not subscription or not subscription.get('endpoint'):
        return jsonify({'error': 'Invalid subscription'}), 400
    
    db = get_db()
    try:
        keys = subscription.get('keys', {})
        
        # Check existing
        existing = db.query(PushSubscription).filter(
            PushSubscription.user_id == current_user.id,
            PushSubscription.endpoint == subscription['endpoint']
        ).first()
        
        if existing:
            existing.p256dh = keys.get('p256dh', existing.p256dh)
            existing.auth = keys.get('auth', existing.auth)
        else:
            sub = PushSubscription(
                user_id=current_user.id,
                endpoint=subscription['endpoint'],
                p256dh=keys.get('p256dh', ''),
                auth=keys.get('auth', '')
            )
            db.add(sub)
        
        db.commit()
        return jsonify({'message': 'Subscribed to push notifications'})
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to subscribe', 'detail': str(e)}), 500
    finally:
        db.close()


@notifications_bp.route('/unsubscribe', methods=['POST'])
@login_required
def unsubscribe():
    data = request.get_json() or {}
    endpoint = data.get('endpoint')
    
    db = get_db()
    try:
        if endpoint:
            db.query(PushSubscription).filter(
                PushSubscription.user_id == current_user.id,
                PushSubscription.endpoint == endpoint
            ).delete()
        else:
            db.query(PushSubscription).filter(
                PushSubscription.user_id == current_user.id
            ).delete()
        
        db.commit()
        return jsonify({'message': 'Unsubscribed'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@notifications_bp.route('/settings', methods=['GET'])
@login_required
def get_settings():
    return jsonify({
        'notify_messages': current_user.notify_messages,
        'notify_groups': current_user.notify_groups,
        'notify_calls': current_user.notify_calls,
        'notify_preview': current_user.notify_preview,
        'notify_sound': current_user.notify_sound,
    })


@notifications_bp.route('/settings', methods=['PUT'])
@login_required
def update_settings():
    data = request.get_json() or {}
    
    db = get_db()
    try:
        user = db.query(User).get(current_user.id)
        
        for field in ['notify_messages', 'notify_groups', 'notify_calls', 'notify_preview', 'notify_sound']:
            if field in data:
                setattr(user, field, bool(data[field]))
        
        db.commit()
        
        return jsonify({
            'message': 'Settings updated',
            'settings': {
                'notify_messages': user.notify_messages,
                'notify_groups': user.notify_groups,
                'notify_calls': user.notify_calls,
                'notify_preview': user.notify_preview,
                'notify_sound': user.notify_sound,
            }
        })
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


def send_push_notification(user_id, title, body, data=None):
    """Send web push notification to user's subscriptions"""
    try:
        from pywebpush import webpush, WebPushException
        from flask import current_app
        
        vapid_private = current_app.config.get('VAPID_PRIVATE_KEY')
        vapid_claims = current_app.config.get('VAPID_CLAIMS')
        
        if not vapid_private:
            return
        
        db = get_db()
        try:
            user = db.query(User).get(user_id)
            if not user:
                return
            
            # Check notification settings
            if data and data.get('type') == 'message' and not user.notify_messages:
                return
            if data and data.get('type') == 'call' and not user.notify_calls:
                return
            
            subs = db.query(PushSubscription).filter(
                PushSubscription.user_id == user_id
            ).all()
            
            payload = json.dumps({
                'title': title if user.notify_preview else 'ESTACLE',
                'body': body if user.notify_preview else 'New notification',
                'data': data or {},
                'icon': '/static/icons/icon-192.png',
                'badge': '/static/icons/badge-72.png',
            })
            
            for sub in subs:
                try:
                    webpush(
                        subscription_info={
                            'endpoint': sub.endpoint,
                            'keys': {
                                'p256dh': sub.p256dh,
                                'auth': sub.auth
                            }
                        },
                        data=payload,
                        vapid_private_key=vapid_private,
                        vapid_claims=vapid_claims
                    )
                except WebPushException as e:
                    if e.response and e.response.status_code in (404, 410):
                        # Subscription expired
                        db.delete(sub)
                        db.commit()
        finally:
            db.close()
    except Exception:
        pass  # Push not critical
