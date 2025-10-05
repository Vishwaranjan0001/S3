import os
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS  # Add this import
from datetime import datetime
from pathlib import Path
from werkzeug.utils import secure_filename
import mimetypes


# Create Flask app
app = Flask(__name__)
CORS(app)  # Add this line


# Simple configuration
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///simple_storage.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size


# Create storage directory
STORAGE_PATH = Path('storage/buckets')
STORAGE_PATH.mkdir(parents=True, exist_ok=True)


# Initialize database
db = SQLAlchemy(app)


# Allowed file extensions
ALLOWED_EXTENSIONS = {
    'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'svg', 'webp'
}


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_file_info(file_path):
    """Get detailed file information"""
    try:
        stat = file_path.stat()
        mime_type, _ = mimetypes.guess_type(str(file_path))

        return {
            'name': file_path.name,
            'size': stat.st_size,
            'size_formatted': format_file_size(stat.st_size),
            'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
            'type': mime_type or 'unknown',
            'extension': file_path.suffix.lower()
        }
    except Exception as e:
        return {
            'name': file_path.name,
            'size': 0,
            'size_formatted': '0 B',
            'modified': 'Unknown',
            'type': 'unknown',
            'extension': file_path.suffix.lower(),
            'error': str(e)
        }


def format_file_size(size_bytes):
    """Format file size in human readable format"""
    if size_bytes == 0:
        return "0 B"

    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1

    return f"{size_bytes:.1f} {size_names[i]}"


# Simple Bucket Model (Database Table) - UNCHANGED
class Bucket(db.Model):
    """Simple bucket model - like a folder in database"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.now)

    def to_dict(self):
        """Convert bucket to dictionary for JSON response"""
        return {
            'id': self.id,
            'name': self.name,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


# Helper Functions - UNCHANGED except for create_bucket_folder
def is_valid_bucket_name(name):
    """Check if bucket name is valid (simple rules)"""
    if not name or len(name) < 3:
        return False, "Name must be at least 3 characters"

    if len(name) > 50:
        return False, "Name too long (max 50 characters)"

    # Only letters, numbers, and dashes allowed
    if not name.replace('-', '').replace('_', '').isalnum():
        return False, "Only letters, numbers, dash and underscore allowed"

    return True, "Valid name"


def create_bucket_folder(bucket_name):
    """Create actual folder on computer"""
    try:
        folder_path = STORAGE_PATH / bucket_name
        folder_path.mkdir(exist_ok=True)
        return True, f"Folder created at {folder_path}"
    except Exception as e:
        return False, f"Error creating folder: {str(e)}"


# EXISTING ROUTES - UNCHANGED
@app.route('/')
def home():
    """Home page - shows API info"""
    return {
        'message': 'Simple Storage Service',
        'endpoints': {
            'create_bucket': 'POST /buckets',
            'list_buckets': 'GET /buckets',
            'get_bucket': 'GET /buckets/<name>',
            'delete_bucket': 'DELETE /buckets/<name>',
            'upload_file': 'POST /buckets/<name>/files',  # NEW
            'list_files': 'GET /buckets/<name>/files',    # NEW
            'download_file': 'GET /buckets/<name>/files/<filename>',  # NEW
            'delete_file': 'DELETE /buckets/<name>/files/<filename>'  # NEW
        }
    }


@app.route('/buckets', methods=['GET'])
def list_buckets():
    """List all buckets - UNCHANGED"""
    try:
        buckets = Bucket.query.all()
        bucket_list = [bucket.to_dict() for bucket in buckets]

        return jsonify({
            'success': True,
            'buckets': bucket_list,
            'count': len(bucket_list)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error listing buckets: {str(e)}'
        }), 500


@app.route('/buckets', methods=['POST'])
def create_bucket():
    """Create a new bucket - UNCHANGED"""
    try:
        data = request.get_json()

        if not data or 'name' not in data:
            return jsonify({
                'success': False,
                'error': 'Please provide bucket name in JSON: {"name": "bucket-name"}'
            }), 400

        bucket_name = data['name'].strip().lower()

        is_valid, message = is_valid_bucket_name(bucket_name)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': message
            }), 400

        existing_bucket = Bucket.query.filter_by(name=bucket_name).first()
        if existing_bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" already exists'
            }), 409

        folder_success, folder_message = create_bucket_folder(bucket_name)
        if not folder_success:
            return jsonify({
                'success': False,
                'error': folder_message
            }), 500

        new_bucket = Bucket(name=bucket_name)
        db.session.add(new_bucket)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Bucket "{bucket_name}" created successfully',
            'bucket': new_bucket.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Error creating bucket: {str(e)}'
        }), 500


@app.route('/buckets/<bucket_name>', methods=['GET'])
def get_bucket(bucket_name):
    """Get information about a specific bucket - UPDATED to include file info"""
    try:
        bucket = Bucket.query.filter_by(name=bucket_name).first()

        if not bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" not found'
            }), 404

        folder_path = STORAGE_PATH / bucket_name
        folder_exists = folder_path.exists()

        # Get files info
        files_info = []
        file_count = 0
        total_size = 0

        if folder_exists:
            for file_path in folder_path.iterdir():
                if file_path.is_file():
                    file_info = get_file_info(file_path)
                    files_info.append(file_info)
                    file_count += 1
                    total_size += file_info.get('size', 0)

        bucket_info = bucket.to_dict()
        bucket_info['folder_exists'] = folder_exists
        bucket_info['file_count'] = file_count
        bucket_info['total_size'] = format_file_size(total_size)
        bucket_info['folder_path'] = str(folder_path)
        bucket_info['files'] = files_info

        return jsonify({
            'success': True,
            'bucket': bucket_info
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error getting bucket: {str(e)}'
        }), 500


@app.route('/buckets/<bucket_name>', methods=['DELETE'])
def delete_bucket(bucket_name):
    """Delete a bucket - UNCHANGED"""
    try:
        bucket = Bucket.query.filter_by(name=bucket_name).first()

        if not bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" not found'
            }), 404

        folder_path = STORAGE_PATH / bucket_name
        if folder_path.exists():
            files = [f for f in folder_path.iterdir() if f.is_file()]
            if files:
                return jsonify({
                    'success': False,
                    'error': f'Bucket has {len(files)} files. Delete files first.'
                }), 400

            try:
                folder_path.rmdir()
            except Exception as e:
                return jsonify({
                    'success': False,
                    'error': f'Error deleting folder: {str(e)}'
                }), 500

        db.session.delete(bucket)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': f'Bucket "{bucket_name}" deleted successfully'
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'Error deleting bucket: {str(e)}'
        }), 500


# NEW FILE UPLOAD ROUTES

@app.route('/buckets/<bucket_name>/files', methods=['POST'])
def upload_file(bucket_name):
    """Upload files to a bucket"""
    try:
        # Check if bucket exists
        bucket = Bucket.query.filter_by(name=bucket_name).first()
        if not bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" not found'
            }), 404

        # Check if files were provided
        if 'files' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No files provided'
            }), 400

        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            return jsonify({
                'success': False,
                'error': 'No files selected'
            }), 400

        bucket_folder = STORAGE_PATH / bucket_name
        bucket_folder.mkdir(exist_ok=True)

        uploaded_files = []
        errors = []

        for file in files:
            if file.filename == '':
                continue

            if not allowed_file(file.filename):
                errors.append(f'File type not allowed: {file.filename}')
                continue

            # Secure the filename
            filename = secure_filename(file.filename)
            if not filename:
                errors.append(f'Invalid filename: {file.filename}')
                continue

            # Check if file already exists
            file_path = bucket_folder / filename
            if file_path.exists():
                # Add timestamp to make unique
                name, ext = filename.rsplit('.', 1) if '.' in filename else (filename, '')
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"{name}_{timestamp}.{ext}" if ext else f"{name}_{timestamp}"
                file_path = bucket_folder / filename

            try:
                file.save(str(file_path))
                file_info = get_file_info(file_path)
                uploaded_files.append(file_info)
            except Exception as e:
                errors.append(f'Failed to save {filename}: {str(e)}')

        if uploaded_files:
            return jsonify({
                'success': True,
                'message': f'Uploaded {len(uploaded_files)} file(s) successfully',
                'files': uploaded_files,
                'errors': errors if errors else None
            })
        else:
            return jsonify({
                'success': False,
                'error': 'No files were uploaded successfully',
                'errors': errors
            }), 400

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error uploading files: {str(e)}'
        }), 500


@app.route('/buckets/<bucket_name>/files', methods=['GET'])
def list_files(bucket_name):
    """List all files in a bucket"""
    try:
        bucket = Bucket.query.filter_by(name=bucket_name).first()
        if not bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" not found'
            }), 404

        bucket_folder = STORAGE_PATH / bucket_name
        if not bucket_folder.exists():
            return jsonify({
                'success': True,
                'files': [],
                'count': 0
            })

        files_info = []
        for file_path in bucket_folder.iterdir():
            if file_path.is_file():
                file_info = get_file_info(file_path)
                files_info.append(file_info)

        # Sort by modified date (newest first)
        files_info.sort(key=lambda x: x['modified'], reverse=True)

        return jsonify({
            'success': True,
            'files': files_info,
            'count': len(files_info)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error listing files: {str(e)}'
        }), 500


@app.route('/buckets/<bucket_name>/files/<filename>', methods=['GET'])
def download_file(bucket_name, filename):
    """Download or view a file"""
    try:
        bucket = Bucket.query.filter_by(name=bucket_name).first()
        if not bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" not found'
            }), 404

        bucket_folder = STORAGE_PATH / bucket_name
        file_path = bucket_folder / filename

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': f'File "{filename}" not found'
            }), 404

        # For images and text files, we can display them inline
        # For PDFs and other files, download them
        mime_type, _ = mimetypes.guess_type(str(file_path))

        if mime_type and (mime_type.startswith('image/') or mime_type == 'text/plain'):
            return send_file(str(file_path), mimetype=mime_type)
        else:
            return send_file(str(file_path), as_attachment=True, download_name=filename)

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error downloading file: {str(e)}'
        }), 500


@app.route('/buckets/<bucket_name>/files/<filename>', methods=['DELETE'])
def delete_file(bucket_name, filename):
    """Delete a file from bucket"""
    try:
        bucket = Bucket.query.filter_by(name=bucket_name).first()
        if not bucket:
            return jsonify({
                'success': False,
                'error': f'Bucket "{bucket_name}" not found'
            }), 404

        bucket_folder = STORAGE_PATH / bucket_name
        file_path = bucket_folder / filename

        if not file_path.exists():
            return jsonify({
                'success': False,
                'error': f'File "{filename}" not found'
            }), 404

        file_path.unlink()  # Delete the file

        return jsonify({
            'success': True,
            'message': f'File "{filename}" deleted successfully'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error deleting file: {str(e)}'
        }), 500


# Run the application - UNCHANGED
if __name__ == '__main__':
    # Create database tables
    with app.app_context():
        db.create_all()
        print("✅ Database ready!")
        print(f"✅ Storage folder created: {STORAGE_PATH}")

    print("🚀 Starting Simple Storage Service with File Upload...")
    print("📍 API will be available at: http://localhost:5000")
    print("📁 Supported file types: TXT, PDF, PNG, JPG, JPEG, GIF, BMP, SVG, WEBP")
    print("📏 Max file size: 50MB")

    app.run(debug=True, port=5000)
