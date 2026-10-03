from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, ForeignKey,
    Float, LargeBinary, Index, UniqueConstraint, Table, Enum as SAEnum
)
from sqlalchemy.orm import relationship, declarative_base, backref
from sqlalchemy.ext.hybrid import hybrid_property
import enum
import secrets
import uuid

Base = declarative_base()

def utcnow():
    return datetime.now(timezone.utc)

# Association tables
conversation_members = Table(
    'conversation_members',
    Base.metadata,
    Column('conversation_id', Integer, ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True),
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('role', String(20), default='member'),  # member, admin, owner
    Column('joined_at', DateTime, default=utcnow),
    Column('muted_until', DateTime, nullable=True),
    Column('is_muted', Boolean, default=False),
    Column('last_read_message_id', Integer, nullable=True),
    Column('notifications_enabled', Boolean, default=True),
)

class MessageStatus(enum.Enum):
    SENDING = 'sending'
    SENT = 'sent'
    DELIVERED = 'delivered'
    READ = 'read'
    FAILED = 'failed'

class CallType(enum.Enum):
    VOICE = 'voice'
    VIDEO = 'video'

class CallStatus(enum.Enum):
    RINGING = 'ringing'
    ONGOING = 'ongoing'
    ENDED = 'ended'
    MISSED = 'missed'
    REJECTED = 'rejected'
    FAILED = 'failed'

class ReportType(enum.Enum):
    USER = 'user'
    MESSAGE = 'message'
    GROUP = 'group'

class User(Base, UserMixin):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=False)
    bio = Column(Text, default='')
    profile_photo = Column(String(500), nullable=True)
    
    is_online = Column(Boolean, default=False)
    last_seen = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    email_verified = Column(Boolean, default=False)
    
    # Privacy settings
    show_last_seen = Column(String(20), default='everyone')  # everyone, contacts, nobody
    show_online_status = Column(String(20), default='everyone')
    show_read_receipts = Column(Boolean, default=True)
    show_typing_indicator = Column(Boolean, default=True)
    profile_visibility = Column(String(20), default='everyone')
    
    # Notification settings
    notify_messages = Column(Boolean, default=True)
    notify_groups = Column(Boolean, default=True)
    notify_calls = Column(Boolean, default=True)
    notify_preview = Column(Boolean, default=True)
    notify_sound = Column(Boolean, default=True)
    
    # Theme
    theme = Column(String(20), default='system')  # light, dark, system
    
    # Relationships
    sessions = relationship('Session', back_populates='user', cascade='all, delete-orphan')
    devices = relationship('Device', back_populates='user', cascade='all, delete-orphan')
    contacts = relationship('Contact', foreign_keys='Contact.user_id', back_populates='user', cascade='all, delete-orphan')
    blocked = relationship('BlockedUser', foreign_keys='BlockedUser.blocker_id', back_populates='blocker', cascade='all, delete-orphan')
    messages = relationship('Message', back_populates='sender', foreign_keys='Message.sender_id')
    reactions = relationship('MessageReaction', back_populates='user', cascade='all, delete-orphan')
    saved_messages = relationship('SavedMessage', back_populates='user', cascade='all, delete-orphan')
    push_subscriptions = relationship('PushSubscription', back_populates='user', cascade='all, delete-orphan')
    reports_made = relationship('Report', foreign_keys='Report.reporter_id', back_populates='reporter')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password, method='scrypt')
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self, include_private=False):
        data = {
            'id': self.id,
            'username': self.username,
            'display_name': self.display_name,
            'bio': self.bio,
            'profile_photo': self.profile_photo,
            'is_online': self.is_online,
            'last_seen': self.last_seen.isoformat() if self.last_seen else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }
        if include_private:
            data.update({
                'email': self.email,
                'theme': self.theme,
                'show_last_seen': self.show_last_seen,
                'show_online_status': self.show_online_status,
                'show_read_receipts': self.show_read_receipts,
                'show_typing_indicator': self.show_typing_indicator,
                'profile_visibility': self.profile_visibility,
                'notify_messages': self.notify_messages,
                'notify_groups': self.notify_groups,
                'notify_calls': self.notify_calls,
                'notify_preview': self.notify_preview,
                'notify_sound': self.notify_sound,
            })
        return data
    
    def __repr__(self):
        return f'<User {self.username}>'


class Session(Base):
    __tablename__ = 'sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_token = Column(String(128), unique=True, nullable=False, index=True)
    device_info = Column(String(500))
    ip_address = Column(String(45))
    user_agent = Column(String(500))
    created_at = Column(DateTime, default=utcnow)
    last_active = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime)
    is_active = Column(Boolean, default=True)
    
    user = relationship('User', back_populates='sessions')
    
    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(64)


class Device(Base):
    __tablename__ = 'devices'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    device_id = Column(String(128), unique=True, nullable=False)
    device_name = Column(String(200))
    device_type = Column(String(50))  # mobile, tablet, desktop
    os_info = Column(String(200))
    browser_info = Column(String(200))
    last_active = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
    is_current = Column(Boolean, default=False)
    
    user = relationship('User', back_populates='devices')


class Contact(Base):
    __tablename__ = 'contacts'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    contact_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    nickname = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    
    user = relationship('User', foreign_keys=[user_id], back_populates='contacts')
    contact_user = relationship('User', foreign_keys=[contact_id])
    
    __table_args__ = (
        UniqueConstraint('user_id', 'contact_id', name='unique_contact'),
    )


class BlockedUser(Base):
    __tablename__ = 'blocked_users'
    
    id = Column(Integer, primary_key=True)
    blocker_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    blocked_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    created_at = Column(DateTime, default=utcnow)
    reason = Column(Text, nullable=True)
    
    blocker = relationship('User', foreign_keys=[blocker_id], back_populates='blocked')
    blocked_user = relationship('User', foreign_keys=[blocked_id])
    
    __table_args__ = (
        UniqueConstraint('blocker_id', 'blocked_id', name='unique_block'),
    )


class Conversation(Base):
    __tablename__ = 'conversations'
    
    id = Column(Integer, primary_key=True)
    type = Column(String(20), default='private')  # private, group
    name = Column(String(200), nullable=True)  # for groups
    description = Column(Text, nullable=True)
    photo = Column(String(500), nullable=True)
    invite_link = Column(String(100), unique=True, nullable=True)
    
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    is_active = Column(Boolean, default=True)
    only_admins_can_post = Column(Boolean, default=False)
    
    # Relationships
    members = relationship('User', secondary=conversation_members, backref=backref('conversations', lazy='dynamic'))
    messages = relationship('Message', back_populates='conversation', cascade='all, delete-orphan', order_by='Message.created_at')
    creator = relationship('User', foreign_keys=[created_by])
    
    def generate_invite_link(self):
        self.invite_link = secrets.token_urlsafe(16)
        return self.invite_link
    
    def to_dict(self, current_user_id=None):
        data = {
            'id': self.id,
            'type': self.type,
            'name': self.name,
            'description': self.description,
            'photo': self.photo,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'only_admins_can_post': self.only_admins_can_post,
            'member_count': len(self.members) if self.members else 0,
        }
        return data


class Message(Base):
    __tablename__ = 'messages'
    
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False, index=True)
    sender_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    
    content = Column(Text, nullable=True)
    message_type = Column(String(30), default='text')  # text, image, video, audio, document, location, contact, system
    
    # Reply / Forward
    reply_to_id = Column(Integer, ForeignKey('messages.id', ondelete='SET NULL'), nullable=True)
    forwarded_from_id = Column(Integer, ForeignKey('messages.id', ondelete='SET NULL'), nullable=True)
    
    # Status
    status = Column(String(20), default='sent')
    is_edited = Column(Boolean, default=False)
    is_deleted_for_everyone = Column(Boolean, default=False)
    is_pinned = Column(Boolean, default=False)
    
    # Location
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_name = Column(String(300), nullable=True)
    
    # Contact share
    shared_contact_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    created_at = Column(DateTime, default=utcnow, index=True)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    edited_at = Column(DateTime, nullable=True)
    
    # Relationships
    conversation = relationship('Conversation', back_populates='messages')
    sender = relationship('User', foreign_keys=[sender_id], back_populates='messages')
    reply_to = relationship('Message', remote_side=[id], foreign_keys=[reply_to_id])
    attachments = relationship('Attachment', back_populates='message', cascade='all, delete-orphan')
    reactions = relationship('MessageReaction', back_populates='message', cascade='all, delete-orphan')
    deletions = relationship('MessageDeletion', back_populates='message', cascade='all, delete-orphan')
    
    __table_args__ = (
        Index('ix_messages_conversation_created', 'conversation_id', 'created_at'),
    )
    
    def to_dict(self, current_user_id=None):
        # Check if deleted for this user
        if current_user_id:
            for d in self.deletions:
                if d.user_id == current_user_id:
                    return None
        
        data = {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'sender_id': self.sender_id,
            'sender': self.sender.to_dict() if self.sender else None,
            'content': None if self.is_deleted_for_everyone else self.content,
            'message_type': self.message_type,
            'status': self.status,
            'is_edited': self.is_edited,
            'is_deleted_for_everyone': self.is_deleted_for_everyone,
            'is_pinned': self.is_pinned,
            'reply_to_id': self.reply_to_id,
            'forwarded_from_id': self.forwarded_from_id,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'location_name': self.location_name,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'edited_at': self.edited_at.isoformat() if self.edited_at else None,
            'attachments': [a.to_dict() for a in self.attachments] if self.attachments else [],
            'reactions': [r.to_dict() for r in self.reactions] if self.reactions else [],
        }
        return data


class MessageDeletion(Base):
    __tablename__ = 'message_deletions'
    
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    deleted_at = Column(DateTime, default=utcnow)
    
    message = relationship('Message', back_populates='deletions')
    
    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', name='unique_message_deletion'),
    )


class Attachment(Base):
    __tablename__ = 'attachments'
    
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    
    filename = Column(String(500), nullable=False)
    original_filename = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=False)
    file_type = Column(String(50))  # image, video, audio, document, archive, other
    mime_type = Column(String(100))
    file_size = Column(Integer)
    duration = Column(Float, nullable=True)  # for audio/video
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    thumbnail_path = Column(String(1000), nullable=True)
    
    created_at = Column(DateTime, default=utcnow)
    
    message = relationship('Message', back_populates='attachments')
    
    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'original_filename': self.original_filename,
            'file_type': self.file_type,
            'mime_type': self.mime_type,
            'file_size': self.file_size,
            'duration': self.duration,
            'width': self.width,
            'height': self.height,
            'url': f'/uploads/{self.filename}',
            'thumbnail_url': f'/uploads/{self.thumbnail_path}' if self.thumbnail_path else None,
        }


class MessageReaction(Base):
    __tablename__ = 'message_reactions'
    
    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    reaction = Column(String(50), nullable=False)  # emoji or reaction type
    created_at = Column(DateTime, default=utcnow)
    
    message = relationship('Message', back_populates='reactions')
    user = relationship('User', back_populates='reactions')
    
    __table_args__ = (
        UniqueConstraint('message_id', 'user_id', 'reaction', name='unique_reaction'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'message_id': self.message_id,
            'user_id': self.user_id,
            'reaction': self.reaction,
            'user': self.user.to_dict() if self.user else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Call(Base):
    __tablename__ = 'calls'
    
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True)
    caller_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    
    call_type = Column(String(20), default='voice')  # voice, video
    status = Column(String(20), default='ringing')
    
    started_at = Column(DateTime, default=utcnow)
    answered_at = Column(DateTime, nullable=True)
    ended_at = Column(DateTime, nullable=True)
    duration = Column(Integer, default=0)  # seconds
    
    # Relationships
    participants = relationship('CallParticipant', back_populates='call', cascade='all, delete-orphan')
    caller = relationship('User', foreign_keys=[caller_id])
    
    def to_dict(self):
        return {
            'id': self.id,
            'conversation_id': self.conversation_id,
            'caller_id': self.caller_id,
            'call_type': self.call_type,
            'status': self.status,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'answered_at': self.answered_at.isoformat() if self.answered_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'duration': self.duration,
            'participants': [p.to_dict() for p in self.participants] if self.participants else [],
        }


class CallParticipant(Base):
    __tablename__ = 'call_participants'
    
    id = Column(Integer, primary_key=True)
    call_id = Column(Integer, ForeignKey('calls.id', ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    
    joined_at = Column(DateTime, nullable=True)
    left_at = Column(DateTime, nullable=True)
    status = Column(String(20), default='invited')  # invited, ringing, joined, left, rejected, missed
    
    call = relationship('Call', back_populates='participants')
    user = relationship('User')
    
    def to_dict(self):
        return {
            'id': self.id,
            'call_id': self.call_id,
            'user_id': self.user_id,
            'user': self.user.to_dict() if self.user else None,
            'joined_at': self.joined_at.isoformat() if self.joined_at else None,
            'left_at': self.left_at.isoformat() if self.left_at else None,
            'status': self.status,
        }


class SavedMessage(Base):
    __tablename__ = 'saved_messages'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    message_id = Column(Integer, ForeignKey('messages.id', ondelete='CASCADE'), nullable=False)
    saved_at = Column(DateTime, default=utcnow)
    note = Column(Text, nullable=True)
    
    user = relationship('User', back_populates='saved_messages')
    message = relationship('Message')
    
    __table_args__ = (
        UniqueConstraint('user_id', 'message_id', name='unique_saved_message'),
    )


class PushSubscription(Base):
    __tablename__ = 'push_subscriptions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    endpoint = Column(Text, nullable=False)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)
    
    user = relationship('User', back_populates='push_subscriptions')


class Report(Base):
    __tablename__ = 'reports'
    
    id = Column(Integer, primary_key=True)
    reporter_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    report_type = Column(String(20), nullable=False)  # user, message, group
    reported_user_id = Column(Integer, ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    reported_message_id = Column(Integer, ForeignKey('messages.id', ondelete='SET NULL'), nullable=True)
    reported_conversation_id = Column(Integer, ForeignKey('conversations.id', ondelete='SET NULL'), nullable=True)
    reason = Column(Text, nullable=False)
    details = Column(Text, nullable=True)
    status = Column(String(20), default='pending')  # pending, reviewed, resolved, dismissed
    created_at = Column(DateTime, default=utcnow)
    
    reporter = relationship('User', foreign_keys=[reporter_id], back_populates='reports_made')


class UserChatSettings(Base):
    __tablename__ = 'user_chat_settings'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    conversation_id = Column(Integer, ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False)
    
    is_pinned = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    is_muted = Column(Boolean, default=False)
    muted_until = Column(DateTime, nullable=True)
    is_unread = Column(Boolean, default=False)
    custom_notification = Column(Boolean, nullable=True)
    
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    
    __table_args__ = (
        UniqueConstraint('user_id', 'conversation_id', name='unique_user_chat_settings'),
    )


class PasswordResetToken(Base):
    __tablename__ = 'password_reset_tokens'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    token = Column(String(128), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False)
    
    user = relationship('User')
    
    @staticmethod
    def generate_token():
        return secrets.token_urlsafe(48)
