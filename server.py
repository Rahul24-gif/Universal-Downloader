import os
import time
import uuid
import threading
import glob
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)
CORS(app)

basedir = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(basedir, 'downloads')
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# In-memory progress tracking
tasks = {}

def cleanup_daemon():
    """Background thread to delete files older than 2 hours in the downloads directory."""
    while True:
        try:
            now = time.time()
            for filename in os.listdir(DOWNLOAD_DIR):
                filepath = os.path.join(DOWNLOAD_DIR, filename)
                if os.path.isfile(filepath):
                    # Check file modification time
                    if os.stat(filepath).st_mtime < now - 2 * 3600:
                        os.remove(filepath)
                        print(f"Auto-cleaned: {filename}")
            # Also clean up old tasks from memory
            to_delete = []
            for t_id, t_info in tasks.items():
                if t_info.get('status') in ('completed', 'error'):
                    if t_info.get('timestamp', 0) < now - 2 * 3600:
                        to_delete.append(t_id)
            for t_id in to_delete:
                del tasks[t_id]
        except Exception as e:
            print(f"Cleanup error: {e}")
        time.sleep(3600)  # Sleep for an hour

# Start the daemon process
threading.Thread(target=cleanup_daemon, daemon=True).start()

def get_base_opts():
    return {
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        },
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'noplaylist': True
    }

@app.route('/')
def index():
    return send_file(os.path.join(basedir, 'index.html'))

@app.route('/api/info', methods=['GET'])
def get_info():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL is required'}), 400

    opts = get_base_opts()
    opts['extract_flat'] = False

    try:
        import concurrent.futures
        def fetch_worker():
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
                
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = executor.submit(fetch_worker)
        try:
            info = future.result(timeout=25)
        except concurrent.futures.TimeoutError:
            executor.shutdown(wait=False, cancel_futures=True)
            return jsonify({'error': 'Network Timeout: The extraction process got stuck due to your internet routing. Try again.'}), 504
            
        # Extract distinct progressive and adaptive formats
        formats = info.get('formats', [])
        video_qualities = set()
        has_audio_only = False
        
        for f in formats:
            # Detect if there's an audio only format
            if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                has_audio_only = True
            
            # Capture possible quality heights
            if f.get('height'):
                video_qualities.add(f.get('height'))
        
        # Sort highest available
        sorted_qualities = sorted(list(video_qualities), reverse=True)
        
        return jsonify({
            'title': info.get('title'),
            'thumbnail': info.get('thumbnail'),
            'duration': info.get('duration'),
            'views': info.get('view_count'),
            'platform': info.get('extractor_key'),
            'qualities': sorted_qualities,
            'audio_only': has_audio_only
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

def download_worker(task_id, url, dl_type, quality):
    tasks[task_id]['status'] = 'starting'
    tasks[task_id]['timestamp'] = time.time()
    
    opts = get_base_opts()
    opts['outtmpl'] = os.path.join(DOWNLOAD_DIR, f"{task_id}.%(ext)s")
    
    def my_hook(d):
        if d['status'] == 'downloading':
            tasks[task_id]['status'] = 'downloading'
            tasks[task_id]['percent'] = d.get('_percent_str', '0.0%').strip()
        elif d['status'] == 'finished':
            tasks[task_id]['status'] = 'processing'
            tasks[task_id]['percent'] = '100%'
            
    opts['progress_hooks'] = [my_hook]
    
    if dl_type == 'audio':
        opts['format'] = 'bestaudio/best'
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }]
    else:
        # Video: combine best video under/at target resolution + best audio
        if quality:
            opts['format'] = f'bestvideo[height<={quality}]+bestaudio/best'
            opts['merge_output_format'] = 'mp4'
        else:
            opts['format'] = 'best'
            
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
            
        # Search the DOWNLOAD_DIR for the exact file name
        # It's generated as task_id.EXT
        files = glob.glob(os.path.join(DOWNLOAD_DIR, f"{task_id}.*"))
        if files:
            tasks[task_id]['status'] = 'completed'
            tasks[task_id]['file'] = os.path.basename(files[0])
        else:
            tasks[task_id]['status'] = 'error'
            tasks[task_id]['error'] = 'Output file not found after download.'
    except Exception as e:
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['error'] = str(e)


@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    if not data or not data.get('url'):
        return jsonify({'error': 'URL is required'}), 400
        
    task_id = str(uuid.uuid4())
    tasks[task_id] = {
        'status': 'queued',
        'percent': '0%',
        'timestamp': time.time(),
        'url': data['url'],
        'title': data.get('title', 'Unknown Title')
    }
    
    dl_type = data.get('type', 'video')
    quality = data.get('quality')
    
    t = threading.Thread(
        target=download_worker,
        args=(task_id, data['url'], dl_type, quality)
    )
    t.start()
    
    return jsonify({'task_id': task_id})

@app.route('/api/progress/<task_id>', methods=['GET'])
def get_progress(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
    return jsonify(tasks[task_id])

@app.route('/api/file/<task_id>', methods=['GET'])
def get_file(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found'}), 404
        
    task = tasks[task_id]
    if task.get('status') != 'completed' or not task.get('file'):
        return jsonify({'error': 'File not ready'}), 400
        
    filepath = os.path.join(DOWNLOAD_DIR, task['file'])
    if not os.path.exists(filepath):
        return jsonify({'error': 'File does not exist on server'}), 500
        
    original_title = task.get('title', 'download')
    ext = os.path.splitext(task['file'])[1]
    download_name = f"{original_title}{ext}"
        
    return send_file(filepath, as_attachment=True, download_name=download_name)

@app.route('/api/cleanup/<task_id>', methods=['DELETE'])
def cleanup_file(task_id):
    if task_id in tasks:
        task = tasks[task_id]
        if task.get('file'):
            filepath = os.path.join(DOWNLOAD_DIR, task['file'])
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except Exception as e:
                    return jsonify({'error': str(e)}), 500
        del tasks[task_id]
        return jsonify({'success': True})
    return jsonify({'error': 'Task not found'}), 404

if __name__ == '__main__':
    # For local testing, accessible fully
    app.run(host='0.0.0.0', port=5000, debug=False)
