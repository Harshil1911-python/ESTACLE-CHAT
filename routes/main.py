from flask import Blueprint, render_template, send_from_directory, current_app
from flask_login import login_required, current_user

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return render_template('index.html')

@main_bp.route('/login')
def login_page():
    return render_template('index.html')

@main_bp.route('/register')
def register_page():
    return render_template('index.html')

@main_bp.route('/chat')
@main_bp.route('/chat/<path:subpath>')
@login_required
def chat_app(subpath=None):
    return render_template('app.html')

@main_bp.route('/offline')
def offline():
    return render_template('offline.html')
