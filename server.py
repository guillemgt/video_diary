from http.server import BaseHTTPRequestHandler, HTTPServer
import cgi
import os
import mimetypes
import time
from pathlib import Path
import threading
import yaml

from merge_videos import process_a_video, merge_videos

config = yaml.safe_load(open('config.yaml'))

class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        # Read a video file, save it and process it

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

            Path(video_file.replace('.mp4', '.lock')).touch()
            threading.Thread(target=process_a_video, args=(video_file, int(file_index), config)).start()

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'File uploaded successfully')
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'Bad request')

    def do_GET(self):
        # Merge the videos, send them and clean up
        
        if 'done' in self.path:

            if config['delete_intermediate_files']:
                for file in os.listdir('tmp/uploads'):
                    os.remove(f'tmp/uploads/{file}')
                os.remove('tmp/combined_video.mp4')

            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'Done')

            return

        # Check if there are files of the form tmp/uploads/*.lock
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
            return
        
        
        if os.path.exists('tmp/process.lock'):
            self.send_response(202)
            self.end_headers()
            self.wfile.write(b'Processing, try again in 1 minute')
            return
        
        # Create lock file and start processing in a new thread
        Path('tmp/process.lock').touch()
        threading.Thread(target=merge_videos, kwargs={
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
    print(f'Starting server on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':

    print("Using config:")
    for key, value in config.items():
        print(f"\t{key}: {value}")

    run()
