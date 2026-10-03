from flask import Blueprint, request, jsonify, current_app
from flask_login import login_required, current_user
from datetime import datetime, timezone
from sqlalchemy import and_, or_

from database.database import get_db
from database.models import Call, CallParticipant, Conversation, conversation_members, User, BlockedUser

calls_bp = Blueprint('calls', __name__)

@calls_bp.route('/config', methods=['GET'])
@login_required
def webrtc_config():
    return jsonify({
        'iceServers': current_app.config.get('WEBRTC_STUN_SERVERS', []) + 
                      current_app.config.get('WEBRTC_TURN_SERVERS', [])
    })


@calls_bp.route('/start', methods=['POST'])
@login_required
def start_call():
    data = request.get_json() or {}
    conversation_id = data.get('conversation_id')
    call_type = data.get('call_type', 'voice')  # voice or video
    target_user_id = data.get('user_id')
    
    if call_type not in ('voice', 'video'):
        return jsonify({'error': 'Invalid call type'}), 400
    
    db = get_db()
    try:
        # Resolve conversation
        if conversation_id:
            member = db.execute(
                conversation_members.select().where(
                    and_(
                        conversation_members.c.conversation_id == conversation_id,
                        conversation_members.c.user_id == current_user.id
                    )
                )
            ).first()
            if not member:
                return jsonify({'error': 'Not a member'}), 403
            conv = db.query(Conversation).get(conversation_id)
        elif target_user_id:
            # Find or create private conversation
            other = db.query(User).filter(User.id == target_user_id, User.is_active == True).first()
            if not other:
                return jsonify({'error': 'User not found'}), 404
            
            # Check blocked
            blocked = db.query(BlockedUser).filter(
                ((BlockedUser.blocker_id == current_user.id) & (BlockedUser.blocked_id == other.id)) |
                ((BlockedUser.blocker_id == other.id) & (BlockedUser.blocked_id == current_user.id))
            ).first()
            if blocked:
                return jsonify({'error': 'Cannot call this user'}), 403
            
            # Find existing private conv
            conv = None
            member_convs = db.query(Conversation).join(
                conversation_members
            ).filter(
                Conversation.type == 'private',
                conversation_members.c.user_id == current_user.id
            ).all()
            
            for c in member_convs:
                ids = [m.id for m in c.members]
                if other.id in ids and len(ids) == 2:
                    conv = c
                    break
            
            if not conv:
                conv = Conversation(type='private', created_by=current_user.id)
                db.add(conv)
                db.flush()
                db.execute(conversation_members.insert().values(
                    conversation_id=conv.id, user_id=current_user.id, role='member'
                ))
                db.execute(conversation_members.insert().values(
                    conversation_id=conv.id, user_id=other.id, role='member'
                ))
        else:
            return jsonify({'error': 'conversation_id or user_id required'}), 400
        
        # Create call
        call = Call(
            conversation_id=conv.id if conv else None,
            caller_id=current_user.id,
            call_type=call_type,
            status='ringing'
        )
        db.add(call)
        db.flush()
        
        # Add participants
        participants = []
        if conv:
            for m in conv.members:
                if m.id != current_user.id:
                    p = CallParticipant(
                        call_id=call.id,
                        user_id=m.id,
                        status='ringing'
                    )
                    db.add(p)
                    participants.append(m)
        
        # Caller as participant
        caller_p = CallParticipant(
            call_id=call.id,
            user_id=current_user.id,
            status='joined',
            joined_at=datetime.now(timezone.utc)
        )
        db.add(caller_p)
        
        db.commit()
        db.refresh(call)
        
        result = call.to_dict()
        
        # Notify via WebSocket
        try:
            from app import socketio
            for p in participants:
                socketio.emit('incoming_call', {
                    'call': result,
                    'caller': current_user.to_dict()
                }, room=f'user_{p.id}')
        except Exception:
            pass
        
        return jsonify({'call': result}), 201
    except Exception as e:
        db.rollback()
        return jsonify({'error': 'Failed to start call', 'detail': str(e)}), 500
    finally:
        db.close()


@calls_bp.route('/<int:call_id>/answer', methods=['POST'])
@login_required
def answer_call(call_id):
    db = get_db()
    try:
        call = db.query(Call).get(call_id)
        if not call or call.status not in ('ringing',):
            return jsonify({'error': 'Call not available'}), 404
        
        participant = db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == current_user.id
        ).first()
        
        if not participant:
            return jsonify({'error': 'Not a participant'}), 403
        
        call.status = 'ongoing'
        call.answered_at = datetime.now(timezone.utc)
        participant.status = 'joined'
        participant.joined_at = datetime.now(timezone.utc)
        db.commit()
        
        result = call.to_dict()
        
        try:
            from app import socketio
            # Notify all participants
            for p in call.participants:
                socketio.emit('call_answered', {
                    'call': result,
                    'answered_by': current_user.to_dict()
                }, room=f'user_{p.user_id}')
        except Exception:
            pass
        
        return jsonify({'call': result})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@calls_bp.route('/<int:call_id>/reject', methods=['POST'])
@login_required
def reject_call(call_id):
    db = get_db()
    try:
        call = db.query(Call).get(call_id)
        if not call:
            return jsonify({'error': 'Call not found'}), 404
        
        participant = db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == current_user.id
        ).first()
        
        if participant:
            participant.status = 'rejected'
        
        # If all rejected or caller ends
        call.status = 'rejected'
        call.ended_at = datetime.now(timezone.utc)
        db.commit()
        
        try:
            from app import socketio
            for p in call.participants:
                socketio.emit('call_rejected', {
                    'call_id': call_id,
                    'rejected_by': current_user.id
                }, room=f'user_{p.user_id}')
        except Exception:
            pass
        
        return jsonify({'message': 'Call rejected'})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@calls_bp.route('/<int:call_id>/end', methods=['POST'])
@login_required
def end_call(call_id):
    db = get_db()
    try:
        call = db.query(Call).get(call_id)
        if not call:
            return jsonify({'error': 'Call not found'}), 404
        
        participant = db.query(CallParticipant).filter(
            CallParticipant.call_id == call_id,
            CallParticipant.user_id == current_user.id
        ).first()
        
        if participant:
            participant.status = 'left'
            participant.left_at = datetime.now(timezone.utc)
        
        if call.status == 'ringing':
            call.status = 'missed'
        else:
            call.status = 'ended'
        
        call.ended_at = datetime.now(timezone.utc)
        if call.answered_at:
            delta = call.ended_at - call.answered_at
            call.duration = int(delta.total_seconds())
        
        db.commit()
        
        try:
            from app import socketio
            for p in call.participants:
                socketio.emit('call_ended', {
                    'call_id': call_id,
                    'ended_by': current_user.id,
                    'duration': call.duration
                }, room=f'user_{p.user_id}')
        except Exception:
            pass
        
        return jsonify({'message': 'Call ended', 'duration': call.duration})
    except Exception:
        db.rollback()
        return jsonify({'error': 'Failed'}), 500
    finally:
        db.close()


@calls_bp.route('/history', methods=['GET'])
@login_required
def call_history():
    limit = min(int(request.args.get('limit', 50)), 100)
    
    db = get_db()
    try:
        # Calls where user is participant
        participant_call_ids = [
            p.call_id for p in db.query(CallParticipant).filter(
                CallParticipant.user_id == current_user.id
            ).all()
        ]
        
        calls = db.query(Call).filter(
            Call.id.in_(participant_call_ids)
        ).order_by(Call.started_at.desc()).limit(limit).all()
        
        return jsonify({
            'calls': [c.to_dict() for c in calls]
        })
    finally:
        db.close()


@calls_bp.route('/signal', methods=['POST'])
@login_required
def signal():
    """WebRTC signaling relay"""
    data = request.get_json() or {}
    target_user_id = data.get('target_user_id')
    signal_data = data.get('signal')
    call_id = data.get('call_id')
    
    if not target_user_id or not signal_data:
        return jsonify({'error': 'target_user_id and signal required'}), 400
    
    try:
        from app import socketio
        socketio.emit('webrtc_signal', {
            'from_user_id': current_user.id,
            'call_id': call_id,
            'signal': signal_data
        }, room=f'user_{target_user_id}')
        return jsonify({'message': 'Signal sent'})
    except Exception as e:
        return jsonify({'error': 'Failed to send signal', 'detail': str(e)}), 500
