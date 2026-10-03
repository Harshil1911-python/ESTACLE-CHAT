import os
import sys
from datetime import datetime, timezone

from flask import Flask, render_template, send_from_directory, jsonify, request, g
from flask_login import LoginManager, current_user
from flask_socketio import SocketIO
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

from config import config
from database.database import init_db, get_db, close_db
from database.models import User

# Extensions
login_manager = LoginManager()
csrf = CSRFProtect()
socketio = SocketIO()

def create_app(config_name=None):
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')
    
    app = Flask(__name__, 
                static_folder='static',
                template_folder='templates')
    
    app.config.from_object(config.get(config_name, config['default']))
    
    # Proxy fix for production
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    
    # Initialize extensions
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.session_protection = 'strong'
    
    csrf.init_app(app)
    
    # Prefer eventlet if installed; otherwise use threading (works out of the box)
    _async_mode = 'threading'
    try:
        import eventlet  # noqa: F401
        _async_mode = 'eventlet'
    except ImportError:
        pass

    socketio.init_app(app,
                      cors_allowed_origins="*",
                      async_mode=_async_mode,
                      logger=False,
                      engineio_logger=False,
                      ping_timeout=60,
                      ping_interval=25)
    
    # Database
    init_db(app)
    app.teardown_appcontext(close_db)
    
    # Register blueprints
    from routes.auth import auth_bp
    from routes.users import users_bp
    from routes.chats import chats_bp
    from routes.groups import groups_bp
    from routes.messages import messages_bp
    from routes.files import files_bp
    from routes.calls import calls_bp
    from routes.notifications import notifications_bp
    from routes.main import main_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(users_bp, url_prefix='/api/users')
    app.register_blueprint(chats_bp, url_prefix='/api/chats')
    app.register_blueprint(groups_bp, url_prefix='/api/groups')
    app.register_blueprint(messages_bp, url_prefix='/api/messages')
    app.register_blueprint(files_bp, url_prefix='/api/files')
    app.register_blueprint(calls_bp, url_prefix='/api/calls')
    app.register_blueprint(notifications_bp, url_prefix='/api/notifications')
    
    # Exempt certain endpoints from CSRF (API with token auth)
    csrf.exempt(auth_bp)
    
    # User loader
    @login_manager.user_loader
    def load_user(user_id):
        db = get_db()
        try:
            return db.query(User).filter(User.id == int(user_id), User.is_active == True).first()
        finally:
            db.close()
    
    # Context processors
    @app.context_processor
    def inject_globals():
        return {
            'app_name': app.config['APP_NAME'],
            'app_version': app.config['APP_VERSION'],
            'current_year': datetime.now().year,
        }
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found'}), 404
        return render_template('index.html'), 200  # SPA fallback
    
    @app.errorhandler(500)
    def server_error(e):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('error.html', error='Server error'), 500
    
    # PWA routes
    @app.route('/manifest.json')
    def manifest():
        return send_from_directory(app.root_path, 'manifest.json', mimetype='application/manifest+json')
    
    @app.route('/service-worker.js')
    def service_worker():
        return send_from_directory(app.root_path, 'service-worker.js', mimetype='application/javascript')
    
    @app.route('/uploads/<path:filename>')
    def uploaded_file(filename):
        return send_from_directory(app.config['UPLOAD_FOLDER'], filename)
    
    # Health check
    @app.route('/health')
    def health():
        return jsonify({'status': 'ok', 'app': app.config['APP_NAME'], 'version': app.config['APP_VERSION']})
    
    # Initialize WebSocket handlers
    from realtime.websocket import init_socketio_handlers
    init_socketio_handlers(socketio)
    
    return app

# Create app instance
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV', 'development') == 'development'
    socketio.run(app, host='0.0.0.0', port=port, debug=debug, use_reloader=debug)
