from http.server import BaseHTTPRequestHandler, HTTPServer
import cgi
import os
import shutil
import mimetypes
import time
from pathlib import Path
import threading
import yaml
import socket
from tqdm import tqdm
import urllib

from merge_videos import process_a_video, merge_videos

# To avoid printing HTTP requests
def log_message(self, format, *args):
    pass
BaseHTTPRequestHandler.log_message = log_message

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        lan_ip = s.getsockname()[0]
        s.close()
        return lan_ip
    except Exception as e:
        print(f"Error obtaining LAN IP: {e}")
        return "???.???.???.???"

config = yaml.safe_load(open('config.yaml'))

# Shared progress variables
processing_lock = threading.Lock()
progress_lock = threading.Lock()
total_received = 0
total_completed = 0
total_files = None

# TQDM progress bars
progress_bar_received = None
progress_bar_completed = None

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        global total_files, total_received, total_completed, progress_bar_received, progress_bar_completed

        if 'plan' in self.path: # Request sent as a form with num={number of files}
            global total_files

            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            form_data = urllib.parse.parse_qs(post_data)
            total_files = int(form_data['num'][0])

            self.send_response(200)
            self.end_headers()
            self.wfile.write("Received".encode("utf-8"))
            return

        ctype, pdict = cgi.parse_header(self.headers.get('Content-Type'))
        if ctype == 'multipart/form-data':
            pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
            fields = cgi.parse_multipart(self.rfile, pdict)
            file_data = fields.get('file')[0]

            file_index = fields.get('index')[0]

            os.makedirs('tmp/uploads', exist_ok=True)

            video_file = f'tmp/uploads/{file_index}.mp4'
            with open(video_file, 'wb') as f:
                f.write(file_data)
            
            # Save the originals if set in the config
            if (originals_path := config.get("copy_original_files_to")) is not None:
                os.makedirs(originals_path, exist_ok=True)
                new_video_file = f'{originals_path}/{file_index}.mp4'
                shutil.copyfile(video_file, new_video_file)

            Path(video_file.replace('.mp4', '.lock')).touch()
            threading.Thread(target=self.process_video, args=(video_file, file_index)).start()

            if progress_bar_completed is None:
                progress_bar_received = tqdm(total=total_files, desc=" Received", position=0)
                progress_bar_completed = tqdm(total=total_files, desc="Completed", position=1)

            with progress_lock:
                total_received += 1
                progress_bar_received.update(1)

            self.send_response(200)
            self.end_headers()
            formatted_str = f"File {file_index} uploaded successfully"
            self.wfile.write(formatted_str.encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Bad request')

    def process_video(self, video_file, file_index):
        global total_completed, progress_bar_completed
        with processing_lock:
            process_a_video(video_file, int(file_index), config)

        with progress_lock:
            total_completed += 1
            progress_bar_completed.update(1)

    def do_GET(self):
        if 'done' in self.path:
            if (save_path := config['save_result_to']) is not None:
                os.makedirs(save_path, exist_ok=True)
                shutil.copyfile('tmp/combined_video.mp4', f'{save_path}/result.mp4')

            if config['delete_intermediate_files']:
                for file in os.listdir('tmp/uploads'):
                    os.remove(f'tmp/uploads/{file}')
                os.remove('tmp/combined_video.mp4')
                os.rmdir('tmp/uploads')
                os.rmdir('tmp')

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Done')
            
            print("Sent the finished video. My work is now complete :)")
            exit(0)
            return

        if any([file.endswith('.lock') for file in os.listdir('tmp/uploads')]):
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b'Processing individual videos...')
            return

        file_path = 'tmp/combined_video.mp4'
        if os.path.exists(file_path) and not os.path.exists('tmp/process.lock'):
            self.send_response(200)
            self.send_header('Content-type', 'video/mp4')
            self.end_headers()
            with open(file_path, 'rb') as file:
                self.wfile.write(file.read())
            filesize_in_mb = os.path.getsize(file_path) // (1024 * 1024)
            print(f"Combined video file size: {filesize_in_mb} MB")
            return

        if os.path.exists('tmp/process.lock'):
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b'Processing, try again in 1 minute')
            return

        if progress_bar_received:
            progress_bar_received.close()
            progress_bar_completed.close()
        Path('tmp/process.lock').touch()
        threading.Thread(target=merge_videos, kwargs={
            'config': config,
            'output_combined_video': file_path,
            'delete_intermediate_files': config['delete_intermediate_files'],
            'lossless': config['lossless']
        }).start()
        self.send_response(202)
        self.end_headers()
        self.wfile.write(b'Processing started, try again in 1 minute')

def run(server_class=HTTPServer, handler_class=SimpleHTTPRequestHandler, port=8080):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"The URL is:\n >>> {get_lan_ip()}:{port} <<<\n")
    httpd.serve_forever()

if __name__ == '__main__':
    print("Using config:")
    for key, value in config.items():
        print(f"\t{key}: {value}")
    print()

    try:
        run()
    except KeyboardInterrupt:
        progress_bar_received.close()
        progress_bar_completed.close()
