from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.pool import StaticPool
from contextlib import contextmanager
import os

from database.models import Base

engine = None
SessionLocal = None

def init_db(app=None):
    global engine, SessionLocal
    
    if app:
        db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    else:
        db_uri = os.environ.get('DATABASE_URL') or 'sqlite:////tmp/estacle.sqlite'
    
    # Ensure instance directory exists
    instance_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'instance')
    os.makedirs(instance_dir, exist_ok=True)
    
    # Ensure uploads directory exists
    uploads_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'uploads')
    os.makedirs(uploads_dir, exist_ok=True)
    
    connect_args = {}
    if db_uri.startswith('sqlite'):
        connect_args = {'check_same_thread': False}
        if ':memory:' in db_uri:
            engine = create_engine(
                db_uri,
                connect_args=connect_args,
                poolclass=StaticPool,
                echo=False
            )
        else:
            engine = create_engine(
                db_uri,
                connect_args=connect_args,
                echo=False
            )
            # Enable foreign keys for SQLite
            @event.listens_for(engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    else:
        engine = create_engine(db_uri, echo=False)
    
    SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
    
    # Create all tables
    Base.metadata.create_all(bind=engine)
    
    return engine

def get_db():
    if SessionLocal is None:
        init_db()
    db = SessionLocal()
    try:
        return db
    except Exception:
        db.close()
        raise

@contextmanager
def get_db_session():
    if SessionLocal is None:
        init_db()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

def close_db(e=None):
    if SessionLocal is not None:
        SessionLocal.remove()
